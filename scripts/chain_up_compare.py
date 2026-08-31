#!/usr/bin/env python3
"""「管线判断 vs UP 判断」每日对比工具（M0-Chain Phase 4 T23）。

用法：
    python scripts/chain_up_compare.py collect [--date 2026-08-30]  # 生成对比草稿（默认今天）
    python scripts/chain_up_compare.py log --date 2026-08-30 --chain ai-pcb-ccl \
        --agreement partial --note "UP更保守"                       # 人工结论落账
    python scripts/chain_up_compare.py stats [--days 30]            # 重合度统计

流程：collect 生成 infra/data/chain_tracking/up_compare_<date>.md（每条命中链
末尾有留白行）→ 人工填写 agree/partial/disagree → log 落账 up_comparison.jsonl
→ stats 看重合度。验收参考线：连续5天重合度 >60%（任务书）。

纯本地：不拉数据、不调 LLM。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v * 100:.1f}%"


def _cmd_collect(args: argparse.Namespace) -> int:
    from investment_engine.chain_tracker.up_compare import collect_compare_draft

    date = args.date or datetime.now().date().isoformat()
    path, matched = collect_compare_draft(date)
    print(f"[chain_up_compare] {date} 命中 {len(matched)} 条链，"
          f"草稿已写入 {path}")
    for cid, claims in matched.items():
        print(f"  - {cid}：{len(claims)} 条 UP 判断")
    if not matched:
        print("  当日无 UP 判断命中任何链（草稿仅留痕）")
    print("  请人工填写每节留白行后用 log 子命令落账")
    return 0


def _cmd_log(args: argparse.Namespace) -> int:
    from investment_engine.chain_tracker.up_compare import log_comparison

    try:
        entry = log_comparison(date=args.date, chain_id=args.chain,
                               agreement=args.agreement, note=args.note)
    except ValueError as e:
        print(f"[chain_up_compare] 落账失败: {e}", file=sys.stderr)
        return 1
    print(f"[chain_up_compare] 已落账: {entry['date']} {entry['chain_id']} "
          f"agreement={entry['agreement']}"
          f"（管线当时 {entry['pipeline_stage'] or '-'} / "
          f"{entry['pipeline_timing'] or '-'}）")
    if entry["note"]:
        print(f"  备注：{entry['note']}")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    from investment_engine.chain_tracker.up_compare import agreement_stats

    s = agreement_stats(days=args.days)
    print(f"[chain_up_compare] 最近 {s['days']} 天对比结论统计"
          f"（{len(s['dates'])} 天有记录）")
    print(f"  总数 {s['total']}：agree={s['agree']} partial={s['partial']} "
          f"disagree={s['disagree']}")
    print(f"  重合度（agree + 0.5×partial）：{_pct(s['overlap_rate'])}；"
          f"完全一致率：{_pct(s['full_rate'])}")
    for cid, c in s["by_chain"].items():
        print(f"  - {cid}: total={c['total']} agree={c['agree']} "
              f"partial={c['partial']} disagree={c['disagree']} "
              f"重合度={_pct(c['overlap_rate'])}")
    print("  验收参考线：连续5天重合度 >60%（M0-Chain Phase 4 任务书）")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="管线判断 vs UP 判断 每日对比（T23）")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("collect", help="生成当日对比草稿（默认今天）")
    pc.add_argument("--date", help="YYYY-MM-DD，默认今天")
    pc.set_defaults(func=_cmd_collect)

    pl = sub.add_parser("log", help="人工对比结论落账")
    pl.add_argument("--date", required=True, help="YYYY-MM-DD")
    pl.add_argument("--chain", required=True, help="chain_id")
    pl.add_argument("--agreement", required=True,
                    choices=["agree", "partial", "disagree"])
    pl.add_argument("--note", default="", help="备注")
    pl.set_defaults(func=_cmd_log)

    ps = sub.add_parser("stats", help="重合度统计")
    ps.add_argument("--days", type=int, default=30, help="统计窗口天数，默认 30")
    ps.set_defaults(func=_cmd_stats)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
