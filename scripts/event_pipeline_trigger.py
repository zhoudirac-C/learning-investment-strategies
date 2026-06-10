#!/usr/bin/env python3
"""P0 事件驱动管线触发器。

功能:
1. 接收新 claims（从 C2 编排输出）→ 写入 pending_review_queue
2. 生成微信友好的审核摘要
3. 接收 config preview 结果 → 写入 pending_review_queue
4. 生成微信友好的 config 建议摘要

用法:
    # 模式1: 接收 claims 并生成审核摘要
    python scripts/event_pipeline_trigger.py claims --batch-file /path/to/claims_batch.yaml

    # 模式2: 生成 config preview 并写入队列
    python scripts/event_pipeline_trigger.py config-preview --days 1

    # 模式3: 查询待审核队列状态
    python scripts/event_pipeline_trigger.py status

Refs: docs/p0-event-driven-pipeline-design.md v1.0
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "src"))

from qing_investment.agent.tools.pending_review_queue import (
    PendingClaim,
    PendingConfigUpdate,
    PendingReviewQueue,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("event_pipeline_trigger")


def _format_claims_for_wechat(claims: list[PendingClaim]) -> str:
    """将 claims 格式化为微信消息。"""
    import yaml

    lines = ["📋 提取到 claims，请审核：\n"]

    for pc in claims:
        try:
            data = yaml.safe_load(pc.claim_yaml)
        except Exception:
            data = {}

        claim_id = data.get("id", f"#{pc.claim_index}")
        claim_type = data.get("claim_type", "unknown")
        statement = data.get("statement", "")
        confidence = data.get("confidence", "medium")
        related = data.get("related_stocks", [])

        # 截断 statement
        stmt_display = statement[:60] + "..." if len(statement) > 60 else statement

        lines.append(f"【{claim_id}】{claim_type}")
        lines.append(f"• {stmt_display}")
        lines.append(f"• 置信度: {confidence}")
        if related:
            lines.append(f"• 相关标的: {', '.join(str(r) for r in related[:3])}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("回复：")
    lines.append("• 「确认」→ 全部入库")
    lines.append("• 「确认 1 2」→ 只入库指定序号")
    lines.append("• 「跳过」→ 全部丢弃")
    lines.append("• 「查看 1」→ 显示完整内容")

    return "\n".join(lines)


def _format_config_for_wechat(updates: list[PendingConfigUpdate]) -> str:
    """将 config updates 格式化为微信消息。"""
    lines = [f"📋 配置更新建议（{len(updates)}条）：\n"]

    for upd in updates:
        sv = upd.suggested_value

        if upd.update_type == "watchlist":
            lines.append(f"【建议 {upd.update_index}】watchlist 更新")
            lines.append(f"• {upd.target_code}: {sv.get('action', 'update')}")
            if "claim_id" in sv:
                lines.append(f"• 新增 linked_claims: {sv['claim_id']}")
            lines.append("")

        elif upd.update_type == "entry_point":
            lines.append(f"【建议 {upd.update_index}】entry_points {sv.get('action', 'create')}")
            lines.append(f"• {upd.target_code} {sv.get('name', '')}")
            if "entry_zone" in sv:
                lines.append(f"• 介入区间: {sv['entry_zone']}")
            if "position_ratio" in sv:
                lines.append(f"• 仓位: {sv['position_ratio']}")
            if "stop_loss" in sv:
                lines.append(f"• 止损: {sv['stop_loss']}")
            if "odds_ratio" in sv:
                lines.append(f"• 赔率: {sv['odds_ratio']}")
            if "claim_basis" in sv:
                basis = sv["claim_basis"][:50] + "..." if len(sv["claim_basis"]) > 50 else sv["claim_basis"]
                lines.append(f"• 依据: {basis}")
            if sv.get("conflict_check"):
                lines.append(f"⚠️ {sv['conflict_check']}")
            lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("回复：")
    lines.append("• 「确认」→ 全部执行")
    lines.append("• 「确认 1」→ 只执行指定序号")
    lines.append("• 「修改 N 字段 值」→ 修改后执行")
    lines.append("• 「跳过」→ 全部忽略")

    return "\n".join(lines)


def cmd_claims(batch_file: str) -> int:
    """处理 claims 审核流程。"""
    import yaml

    batch_path = Path(batch_file)
    if not batch_path.exists():
        logger.error("Claims batch file not found: %s", batch_file)
        return 1

    with open(batch_path, encoding="utf-8") as f:
        batch_data = yaml.safe_load(f)

    claims_list = batch_data if isinstance(batch_data, list) else batch_data.get("claims", [])
    if not claims_list:
        print("📋 未发现 claims")
        return 0

    # 转换为 PendingClaim
    pending_claims = []
    for claim in claims_list:
        yaml_str = yaml.dump(claim, allow_unicode=True, sort_keys=False)
        pending_claims.append(
            PendingClaim(
                claim_yaml=yaml_str,
                source_file=str(batch_path),
            )
        )

    # 写入队列
    queue = PendingReviewQueue()
    batch_id = queue.add_claims(pending_claims)
    logger.info("Added %d claims to queue, batch_id=%s", len(pending_claims), batch_id)

    # 输出微信消息
    pending = queue.get_pending_claims(batch_id)
    msg = _format_claims_for_wechat(pending)
    print(msg)

    return 0


def cmd_config_preview(days: int) -> int:
    """生成 config preview 并写入队列。"""
    from qing_investment.agent.tools.claims_to_entry import generate_preview_result
    from qing_investment.agent.tools.neo4j_client import Neo4jClient

    logger.info("生成 config preview (days=%d)...", days)

    try:
        neo4j = Neo4jClient()
    except Exception as e:
        logger.error("Neo4j 连接失败: %s", e)
        return 1

    try:
        preview = generate_preview_result(neo4j, days_back=days)
    except Exception as e:
        logger.error("生成 preview 失败: %s", e)
        return 1

    if preview["new_claims_count"] == 0:
        print("📋 未发现新的 config 更新建议")
        return 0

    # 转换为 PendingConfigUpdate 并写入队列
    queue = PendingReviewQueue()

    updates = []
    for wu in preview.get("watchlist_updates", []):
        updates.append(
            PendingConfigUpdate(
                update_type="watchlist",
                target_code=wu["code"],
                suggested_value={
                    "action": wu["action"],
                    "claim_id": wu.get("claim_id", ""),
                },
                rationale=wu.get("rationale", ""),
            )
        )

    for es in preview.get("entry_points_suggestions", []):
        updates.append(
            PendingConfigUpdate(
                update_type="entry_point",
                target_code=es["code"],
                suggested_value={
                    "action": es["action"],
                    "name": es.get("name", ""),
                    "entry_zone": es.get("entry_zone", ""),
                    "position_ratio": es.get("position_ratio", ""),
                    "stop_loss": es.get("stop_loss", ""),
                    "odds_ratio": es.get("odds_ratio", ""),
                    "claim_basis": es.get("claim_basis", ""),
                    "conflict_check": es.get("conflict_check"),
                },
                rationale=es.get("rationale", ""),
            )
        )

    if not updates:
        print("📋 未发现可执行的 config 更新")
        return 0

    batch_id = queue.add_config_updates(updates)
    logger.info("Added %d config updates to queue, batch_id=%s", len(updates), batch_id)

    # 输出微信消息
    pending = queue.get_pending_config_updates(batch_id)
    msg = _format_config_for_wechat(pending)
    print(msg)

    return 0


def cmd_status() -> int:
    """查询待审核队列状态。"""
    queue = PendingReviewQueue()
    batches = queue.get_all_pending_batches()

    if not batches:
        print("📭 待审核队列为空")
        return 0

    lines = ["📋 待审核任务：\n"]
    for batch in batches:
        bid = batch["batch_id"]
        has_claims = "✅" if batch["has_claims"] else "❌"
        has_config = "✅" if batch["has_config"] else "❌"
        lines.append(f"• {bid[:8]}... | Claims:{has_claims} Config:{has_config} | {batch['latest'][:16]}")

    print("\n".join(lines))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="P0 事件驱动管线触发器")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # claims 子命令
    claims_parser = subparsers.add_parser("claims", help="处理 claims 审核")
    claims_parser.add_argument("--batch-file", required=True, help="claims batch YAML 文件路径")

    # config-preview 子命令
    config_parser = subparsers.add_parser("config-preview", help="生成 config 预览")
    config_parser.add_argument("--days", type=int, default=1, help="扫描最近 N 天的 claims")

    # status 子命令
    subparsers.add_parser("status", help="查看待审核队列状态")

    args = parser.parse_args()

    if args.command == "claims":
        return cmd_claims(args.batch_file)
    elif args.command == "config-preview":
        return cmd_config_preview(args.days)
    elif args.command == "status":
        return cmd_status()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
