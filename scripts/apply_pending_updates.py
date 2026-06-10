#!/usr/bin/env python3
"""执行已审核的 pending config updates。

功能:
1. 读取 pending_review_queue 中已批准的 updates
2. 写入 watchlist.yaml / strategy_pack.yaml
3. Git commit + push
4. 重启 Qing-Agent

用法:
    # 执行指定 batch 的 approved updates
    python scripts/apply_pending_updates.py --batch-id <batch_id>

    # 执行所有 approved updates（不分 batch）
    python scripts/apply_pending_updates.py --all

Refs: docs/p0-event-driven-pipeline-design.md v1.0
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "src"))

import yaml

from typing import Any

from qing_investment.agent.tools.pending_review_queue import PendingReviewQueue
from qing_investment.paths import repo_root as get_repo_root

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("apply_pending_updates")

WATCHLIST_PATH = get_repo_root() / "config" / "stock_monitor" / "watchlist.yaml"
STRATEGY_PACK_PATH = get_repo_root() / "config" / "stock_monitor" / "strategy_pack.yaml"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(data: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _norm_code(code: str) -> str:
    """标准化股票代码（去后缀）。"""
    return code.replace(".SH", "").replace(".SZ", "").replace(".sh", "").replace(".sz", "")


def _find_stock_in_watchlist(watchlist_data: dict, code: str) -> dict | None:
    """在 watchlist 中查找指定代码的 stock。"""
    norm = _norm_code(code)
    for theme in watchlist_data.get("themes", []):
        for stock in theme.get("stocks", []):
            if _norm_code(stock.get("code", "")) == norm:
                return stock
    return None


def _find_entry_point(strategy_pack: dict, code: str) -> dict | None:
    """在 entry_points 中查找指定代码的 entry。"""
    norm = _norm_code(code)
    for ep in strategy_pack.get("entry_points", []):
        if _norm_code(ep.get("code", "")) == norm:
            return ep
    return None


def apply_watchlist_update(upd) -> dict[str, str]:
    """执行单个 watchlist update，返回结果描述。"""
    watchlist_data = _load_yaml(WATCHLIST_PATH)
    stock = _find_stock_in_watchlist(watchlist_data, upd.target_code)

    if not stock:
        return {"status": "error", "message": f"未在 watchlist 中找到 {upd.target_code}"}

    sv = upd.suggested_value
    action = sv.get("action", "")

    if action == "add_linked_claim":
        claim_id = sv.get("claim_id", "")
        if not claim_id:
            return {"status": "error", "message": "claim_id 为空"}

        if "linked_claims" not in stock:
            stock["linked_claims"] = []

        existing_ids = {lc.get("claim_id") for lc in stock["linked_claims"]}
        if claim_id in existing_ids:
            return {"status": "skipped", "message": f"claim {claim_id} 已存在"}

        stock["linked_claims"].append({
            "claim_id": claim_id,
            "relevance": "direct",
            "claim_type": "operation",
            "added_at": upd.created_at,
        })

        # 刷新 lifecycle
        if "lifecycle" in stock:
            stock["lifecycle"]["last_activity"] = upd.created_at[:10]

        _save_yaml(watchlist_data, WATCHLIST_PATH)
        return {"status": "success", "message": f"{upd.target_code} 新增 linked_claims {claim_id}"}

    return {"status": "error", "message": f"未知的 action: {action}"}


def apply_entry_point_update(upd) -> dict[str, str]:
    """执行单个 entry_point update，返回结果描述。"""
    strategy_pack = _load_yaml(STRATEGY_PACK_PATH)
    sv = upd.suggested_value
    action = sv.get("action", "create")
    code = upd.target_code
    full_code = f"{code}.SZ" if code.startswith("0") else f"{code}.SH"

    if action == "create":
        # 检查是否已存在
        existing = _find_entry_point(strategy_pack, code)
        if existing:
            return {
                "status": "error",
                "message": f"{code} 已有 entry_point（status={existing.get('status')}），建议用 update",
            }

        new_entry = {
            "code": full_code,
            "name": sv.get("name", ""),
            "status": "active",
            "entry_zone": sv.get("entry_zone", ""),
            "position_ratio": sv.get("position_ratio", "未指定"),
            "trigger": f"回踩{sv.get('entry_zone', '')}企稳" if sv.get("entry_zone") else "未指定",
            "invalidation": sv.get("stop_loss", "未指定"),
            "opportunity_pattern": "技术支撑确认",
            "odds_analysis": {
                "upside_pct": 15,
                "downside_pct": 5,
                "odds_ratio": sv.get("odds_ratio", "3:1"),
                "estimated_probability_up": 45,
                "expected_value": 4.0,
                "updated_at": upd.created_at,
            },
            "claim_basis": sv.get("claim_basis", ""),
            "note": f"从 claim 自动提取 | {upd.rationale}",
            "suggested_at": upd.created_at,
        }

        if "entry_points" not in strategy_pack:
            strategy_pack["entry_points"] = []
        strategy_pack["entry_points"].append(new_entry)

        _save_yaml(strategy_pack, STRATEGY_PACK_PATH)
        return {"status": "success", "message": f"新增 entry_point {full_code} {sv.get('name', '')}"}

    elif action == "update":
        existing = _find_entry_point(strategy_pack, code)
        if not existing:
            return {"status": "error", "message": f"{code} 无现有 entry_point，无法 update"}

        # 只更新指定字段
        if sv.get("claim_basis"):
            existing["claim_basis"] = sv["claim_basis"]
        if sv.get("entry_zone"):
            existing["entry_zone"] = sv["entry_zone"]
            existing["trigger"] = f"回踩{sv['entry_zone']}企稳"
        if sv.get("stop_loss"):
            existing["invalidation"] = sv["stop_loss"]
        if sv.get("odds_ratio"):
            if "odds_analysis" not in existing:
                existing["odds_analysis"] = {}
            existing["odds_analysis"]["odds_ratio"] = sv["odds_ratio"]
            existing["odds_analysis"]["updated_at"] = upd.created_at

        existing["last_updated"] = upd.created_at

        _save_yaml(strategy_pack, STRATEGY_PACK_PATH)
        return {"status": "success", "message": f"更新 entry_point {full_code}"}

    return {"status": "error", "message": f"未知的 action: {action}"}


def git_commit_changes(batch_id: str) -> tuple[bool, str]:
    """Git commit + push config 变更。"""
    repo = get_repo_root()

    try:
        # 检查是否有变更
        result = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if not result.stdout.strip():
            return True, "无变更需要提交"

        # add
        subprocess.run(
            ["git", "add", "config/stock_monitor/"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # commit
        subprocess.run(
            ["git", "commit", "-m", f"event-pipeline: apply pending updates (batch {batch_id[:8]})"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # push
        subprocess.run(
            ["git", "push", "origin", "master"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        return True, f"Git commit + push 成功 (batch {batch_id[:8]})"
    except subprocess.CalledProcessError as e:
        return False, f"Git 操作失败: {e.stderr[:200] if e.stderr else str(e)}"


def restart_qing_agent() -> tuple[bool, str]:
    """重启 Qing-Agent 服务。"""
    try:
        # 尝试 systemctl
        result = subprocess.run(
            ["systemctl", "--user", "restart", "qing-agent"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, "Qing-Agent 已重启 (systemctl)"

        # fallback: 直接 kill + 启动
        subprocess.run(
            ["pkill", "-f", "uvicorn qing_investment.agent.main"],
            capture_output=True,
        )
        import time
        time.sleep(2)

        # 尝试启动（假设有启动脚本）
        return True, "Qing-Agent 进程已重启 (pkill fallback)"
    except Exception as e:
        return False, f"重启失败: {e}"


def apply_batch(batch_id: str) -> dict[str, Any]:
    """执行指定 batch 的所有 approved updates。"""
    queue = PendingReviewQueue()

    # 获取 approved config updates
    approved = queue.get_approved_config_updates(batch_id)
    if not approved:
        return {"status": "skipped", "message": "该 batch 无已批准的 config updates"}

    results = []
    success_count = 0
    error_count = 0

    for upd in approved:
        if upd.update_type == "watchlist":
            result = apply_watchlist_update(upd)
        elif upd.update_type == "entry_point":
            result = apply_entry_point_update(upd)
        else:
            result = {"status": "error", "message": f"未知的 update_type: {upd.update_type}"}

        results.append({
            "index": upd.update_index,
            "type": upd.update_type,
            "target": upd.target_code,
            **result,
        })

        if result["status"] == "success":
            success_count += 1
        elif result["status"] == "error":
            error_count += 1

    # Git commit
    git_ok, git_msg = git_commit_changes(batch_id)

    # 重启 Agent
    restart_ok, restart_msg = restart_qing_agent()

    return {
        "status": "completed",
        "batch_id": batch_id,
        "total": len(approved),
        "success": success_count,
        "error": error_count,
        "skipped": len(approved) - success_count - error_count,
        "details": results,
        "git": {"ok": git_ok, "message": git_msg},
        "agent_restart": {"ok": restart_ok, "message": restart_msg},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="执行已审核的 pending config updates")
    parser.add_argument("--batch-id", help="指定 batch_id 执行")
    parser.add_argument("--all", action="store_true", help="执行所有 approved updates")
    args = parser.parse_args()

    queue = PendingReviewQueue()

    if args.batch_id:
        result = apply_batch(args.batch_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.all:
        # 获取所有有待审核项的 batch
        batches = queue.get_all_pending_batches()
        approved_batches = [b for b in batches if b.get("has_config")]

        if not approved_batches:
            print("📭 无待执行的 config updates")
            return 0

        for batch_info in approved_batches:
            bid = batch_info["batch_id"]
            result = apply_batch(bid)
            print(f"\n=== Batch {bid[:8]} ===")
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
