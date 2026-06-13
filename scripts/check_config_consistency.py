#!/usr/bin/env python3
"""
Config 一致性交叉检查脚本 — qing-stock-monitor-update 门禁。

检查维度（7项）：
  1. strategy_pack 过期检测
  2. watchlist 缺口（claims 方向 vs themes）
  3. watchlist ↔ strategy_pack 对齐
  4. positions 自检
  5. invalidation 点位过期
  6. cron 对齐
  7. claims 一致性

输出 JSON，字段：
  { "pass": bool, "issues": [...], "summary": "..." }
退出码：0=干净, 1=有警告, 2=有错误
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

CN_TZ = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config" / "stock_monitor"
CLAIMS_DIR = REPO_ROOT / "knowledge" / "claims"
CRON_OUTPUT_DIR = Path.home() / ".hermes" / "cron" / "output"

P0, P1, P2 = "P0", "P1", "P2"


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _days_ago(date_str: str) -> int | None:
    """Return days since date_str, or None if unparseable."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(str(date_str).strip("'"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CN_TZ)
            return (datetime.now(CN_TZ) - dt).days
        except (ValueError, TypeError):
            continue
    return None


# ── 1. strategy_pack 过期检测 ────────────────────────────────

def check_strategy_pack_staleness(sp: dict) -> list[dict]:
    issues = []
    updated = sp.get("updated_at", "")
    days = _days_ago(updated)

    if days is not None and days > 3:
        issues.append({"level": P1, "dim": "strategy_pack过期",
                       "msg": f"updated_at={updated}，{days}天前", "fix": "更新 updated_at 和 market_framework"})

    mf = sp.get("market_framework", {})
    stage = mf.get("current_stage", "")
    core_q = mf.get("core_question", "")

    # Check direction keywords staleness
    stale_directions = ["燃气轮机", "工程机械", "创新药", "4000点防守", "4120突破"]
    found_stale = [d for d in stale_directions if d in stage or d in core_q]
    if found_stale:
        issues.append({"level": P0, "dim": "strategy_pack过期",
                       "msg": f"含有过期方向词: {found_stale}",
                       "fix": f"更新 market_framework 对齐当前主线（上游材料/半导体/硅片）"})

    # Check up_quote date
    up_quote = mf.get("up_quote", "")
    quote_days = _days_ago(up_quote[:10]) if up_quote else None
    if quote_days is not None and quote_days > 2:
        issues.append({"level": P1, "dim": "strategy_pack过期",
                       "msg": f"up_quote 日期 {up_quote[:10]}，{quote_days}天前", "fix": "更新 up_quote"})

    return issues


# ── 2. watchlist 缺口检测 ────────────────────────────────────

def check_watchlist_gaps(watchlist: dict, claims: list[dict]) -> list[dict]:
    issues = []
    themes = {t.get("id", ""): t.get("name", "") for t in watchlist.get("themes", [])}
    theme_stocks = {}
    for t in watchlist.get("themes", []):
        for s in t.get("stocks", []):
            theme_stocks[s.get("code", "")] = t.get("id", "")

    # Extract direction claims with related_stocks
    for c in claims:
        if c.get("claim_type") not in ("sector-theme", "operation"):
            continue
        subject = c.get("subject", "")
        stocks = c.get("related_stocks", []) or []

        for s in stocks:
            code = s.get("code", "") if isinstance(s, dict) else str(s)
            if code and code not in theme_stocks:
                name = s.get("name", "") if isinstance(s, dict) else ""
                issues.append({"level": P1, "dim": "watchlist缺口",
                               "msg": f"claim '{subject}' 提到 {name}({code}) 但不在 watchlist",
                               "fix": f"将 {name} 加入 watchlist 对应 theme",
                               "claim_id": c.get("id", "")})

    return issues


# ── 3. watchlist ↔ strategy_pack 对齐 ───────────────────────

def check_watchlist_strategy_alignment(watchlist: dict, sp: dict) -> list[dict]:
    issues = []
    theme_ids = {t.get("id", "") for t in watchlist.get("themes", [])}
    sector_ids = {g.get("id", "") for g in sp.get("sector_groups", [])}

    only_theme = theme_ids - sector_ids
    only_sector = sector_ids - theme_ids

    if only_theme:
        issues.append({"level": P1, "dim": "watchlist↔strategy",
                       "msg": f"watchlist 有 {len(only_theme)} 个 theme 不在 sector_groups",
                       "fix": "创建对应 sector_group"})

    if only_sector:
        issues.append({"level": P2, "dim": "watchlist↔strategy",
                       "msg": f"sector_groups 有 {len(only_sector)} 个组不在 watchlist（可能是旧组）",
                       "fix": "降级为 monitor_only 或删除"})

    return issues


# ── 4. positions 自检 ─────────────────────────────────────

def check_positions(positions: dict) -> list[dict]:
    issues = []
    for acct in positions.get("accounts", []):
        for pos in acct.get("positions", []):
            code = pos.get("code", "")
            shares = pos.get("shares", 0)
            risk_zone = pos.get("risk_zone", "")
            reduce_zone = pos.get("reduce_zone", "")

            if shares <= 0:
                continue

            if not risk_zone and not pos.get("risk_line"):
                issues.append({"level": P0, "dim": "positions缺失",
                               "msg": f"{pos.get('name','')}({code}) 未配置 risk_zone",
                               "fix": "配置 risk_zone 风控区间"})

            if not reduce_zone:
                issues.append({"level": P1, "dim": "positions缺失",
                               "msg": f"{pos.get('name','')}({code}) 未配置 reduce_zone",
                               "fix": "配置 reduce_zone 减仓区间"})

    return issues


# ── 5. invalidation 点位过期 ──────────────────────────────

def check_invalidation_points(sp: dict) -> list[dict]:
    issues = []
    inv_conds = sp.get("invalidation_conditions", sp.get("market_framework", {}).get("invalidation_conditions", []))
    if not inv_conds:
        return issues

    # Find numeric thresholds
    for cond in inv_conds:
        nums = re.findall(r'(\d{3,5})', str(cond))
        for n in nums:
            val = int(n)
            if 3500 < val < 4500:
                # This is an index-level number
                issues.append({"level": P1, "dim": "invalidation点位",
                               "msg": f"invalidation 含数字点位 {val}（如'跌破{val}'），可能已过期",
                               "fix": f"基于当前全A指数实际位置更新阈值。原始: {cond}"})

    return issues


# ── 6. cron 对齐 ──────────────────────────────────────────

def check_cron_alignment(sp: dict) -> list[dict]:
    issues = []
    schedule = sp.get("agent_analysis_schedule", [])
    if not schedule:
        issues.append({"level": P0, "dim": "cron对齐",
                       "msg": "strategy_pack 缺少 agent_analysis_schedule",
                       "fix": "添加 agent_analysis_schedule 字段"})
        return issues

    for entry in schedule:
        focus = entry.get("focus", "")
        # Check for stale direction keywords in cron focus
        stale = ["燃气轮机", "工程机械", "创新药", "4000", "4120"]
        found = [s for s in stale if s in focus]
        if found:
            issues.append({"level": P0, "dim": "cron对齐",
                           "msg": f"{entry.get('time')} '{entry.get('name','')}' focus 含过期方向: {found}",
                           "fix": f"更新 focus 对齐当前主线"})

    return issues


# ── 7. claims 一致性 ─────────────────────────────────────

def check_claims_consistency(sp: dict) -> list[dict]:
    issues = []
    source_claims = sp.get("source_claims", [])
    if not source_claims:
        issues.append({"level": P2, "dim": "claims一致性",
                       "msg": "strategy_pack.source_claims 为空", "fix": "添加当前依据的 claim 列表"})
        return issues

    # Check if any source claim paths exist
    missing = []
    for sc in source_claims:
        if isinstance(sc, str) and sc.endswith(".yaml"):
            full = REPO_ROOT / sc
            if not full.exists():
                missing.append(sc)
    if missing:
        issues.append({"level": P1, "dim": "claims一致性",
                       "msg": f"{len(missing)} 个 source_claim 文件不存在", "fix": "更新或移除过期路径"})

    return issues


# ── 8. watchlist 字段校验 ───────────────────────────────

VALID_PRIORITIES = {"P1-核心", "P2-重点", "P2-观察", "P3-观察", "P3-弹性", "P4-锚点"}
VALID_STAGES = {"watching", "active", "archived", "entered", "monitor_only"}
VALID_SENTIMENTS = {"积极观察", "中性提及", "明确规避", "未提及", None}
VALID_RELEVANCE = {"direct", "indirect"}

def check_watchlist_fields(watchlist: dict) -> list[dict]:
    issues = []
    for theme in watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            code = stock.get("code", "")
            name = stock.get("name", "?")

            # code format
            if code and not re.match(r'^\d{6}\.(SZ|SH)$', code):
                issues.append({"level": P0, "dim": "字段校验",
                               "msg": f"{name} code '{code}' 格式错误（应为 XXXXXX.SZ/SH）",
                               "fix": f"修正 code 为标准格式"})

            # priority
            pri = stock.get("priority")
            if pri and pri not in VALID_PRIORITIES:
                issues.append({"level": P1, "dim": "字段校验",
                               "msg": f"{name}({code}) priority='{pri}' 不合法",
                               "fix": f"修正为 {VALID_PRIORITIES}"})

            # lifecycle.stage
            stage = (stock.get("lifecycle") or {}).get("stage")
            if stage and stage not in VALID_STAGES:
                issues.append({"level": P1, "dim": "字段校验",
                               "msg": f"{name}({code}) lifecycle.stage='{stage}' 不合法",
                               "fix": f"修正为 {VALID_STAGES}"})

            # linked_claims
            for lc in stock.get("linked_claims", []) or []:
                if not lc.get("claim_id"):
                    issues.append({"level": P1, "dim": "字段校验",
                                   "msg": f"{name}({code}) linked_claims 缺 claim_id",
                                   "fix": "补充 claim_id"})
                if lc.get("relevance") not in VALID_RELEVANCE:
                    issues.append({"level": P2, "dim": "字段校验",
                                   "msg": f"{name}({code}) linked_claims relevance='{lc.get('relevance')}' 不合法",
                                   "fix": "修正为 direct/indirect"})

            # up_mention_status.sentiment
            sent = (stock.get("up_mention_status") or {}).get("sentiment")
            if sent is not None and sent not in VALID_SENTIMENTS:
                issues.append({"level": P2, "dim": "字段校验",
                               "msg": f"{name}({code}) sentiment='{sent}' 不合法",
                               "fix": f"修正为 {VALID_SENTIMENTS}"})

    return issues


# ── Main ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Config 一致性交叉检查")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--config-dir", default=str(CONFIG_DIR))
    parser.add_argument("--days", type=int, default=7, help="claims 扫描天数")
    args = parser.parse_args()

    config_dir = Path(args.config_dir)
    sp = load_yaml(config_dir / "strategy_pack.yaml")
    wl = load_yaml(config_dir / "watchlist.yaml")
    pos = load_yaml(config_dir / "positions.yaml")

    # Gather recent claims
    claims = []
    cutoff = datetime.now(CN_TZ) - timedelta(days=args.days)
    for f in sorted(CLAIMS_DIR.glob("claim-*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            for c in (data.get("claims", []) or []):
                sd = c.get("source_date", "")
                try:
                    sd_dt = datetime.strptime(str(sd)[:10], "%Y-%m-%d").replace(tzinfo=CN_TZ)
                    if sd_dt >= cutoff:
                        claims.append(c)
                except (ValueError, TypeError):
                    continue
        except Exception:
            continue

    all_issues = []
    all_issues.extend(check_strategy_pack_staleness(sp))
    all_issues.extend(check_watchlist_gaps(wl, claims))
    all_issues.extend(check_watchlist_strategy_alignment(wl, sp))
    all_issues.extend(check_positions(pos))
    all_issues.extend(check_invalidation_points(sp))
    all_issues.extend(check_cron_alignment(sp))
    all_issues.extend(check_claims_consistency(sp))
    all_issues.extend(check_watchlist_fields(wl))

    p0 = [i for i in all_issues if i["level"] == P0]
    p1 = [i for i in all_issues if i["level"] == P1]
    p2 = [i for i in all_issues if i["level"] == P2]

    summary = f"共 {len(all_issues)} 个问题: P0={len(p0)}, P1={len(p1)}, P2={len(p2)}"
    exit_code = 2 if p0 else (1 if p1 else 0)

    if args.json:
        print(json.dumps({
            "pass": exit_code == 0,
            "summary": summary,
            "exit_code": exit_code,
            "issues": all_issues,
            "p0_count": len(p0),
            "p1_count": len(p1),
            "p2_count": len(p2),
        }, ensure_ascii=False, indent=2))
    else:
        print(f"=== Config 一致性检查 {summary} ===\n")
        for level, label in [(P0, "🔴 P0 - 必须修复"), (P1, "🟡 P1 - 建议修复"), (P2, "🟢 P2 - 可选")]:
            items = [i for i in all_issues if i["level"] == level]
            if not items:
                continue
            print(f"\n## {label} ({len(items)})\n")
            for i in items:
                print(f"  [{i['dim']}] {i['msg']}")
                print(f"    → {i['fix']}\n")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
