#!/usr/bin/env python3
"""产业链跟踪引擎（M0-Chain Phase 2 引擎 B）——30 分钟 tick 入口。

用法：
    python scripts/chain_tracker.py                  # 正常 tick（拉取当日研报/公告/期货）
    python scripts/chain_tracker.py --offline        # 只用本地 infra/data/research 文件
    python scripts/chain_tracker.py --date 2026-08-28 --offline   # 回放某天
    python scripts/chain_tracker.py --no-llm         # 只做匹配不落 LLM 账（调试匹配用）
    python scripts/chain_tracker.py --dry-run        # 预览：不写 DB/chain.yaml/报告

cron 注意：LLM 优先走 Hermes 全局模型配置（resolve_runtime_provider，跟随
~/.hermes/config.yaml 的 model.default，不写死）；全局不可用时回落 .env 通道
（SENSENOVA_API_KEY / DEEPSEEK_API_KEY → ZHIPU_API_KEY 的 GLM）。本脚本自身不读
.env——经 ~/.hermes/scripts/qing_chain_tracker.py 包装脚本调度（自动注入 .env）。

产物：
    infra/data/chain_tracking/processed_items.db     去重 DB（48h TTL）
    infra/data/chain_tracking/daily_report_<date>.md 增量日报（仅有变化的链）
    infra/data/chain_tracking/ticks.jsonl            每 tick 机器可读摘要
    infra/data/chain_tracking/futures_state.json     期货告警防抖状态
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.chain_tracker.core import run_tick  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="产业链跟踪引擎 30 分钟 tick")
    p.add_argument("--date", help="YYYY-MM-DD，默认今天")
    p.add_argument("--offline", action="store_true",
                   help="只用本地 research 文件，不拉取")
    p.add_argument("--no-llm", action="store_true",
                   help="只做去重+匹配，不调 LLM（matched 项不落账，留给真实跑）")
    p.add_argument("--dry-run", action="store_true",
                   help="预览：不写 DB/chain.yaml/报告")
    args = p.parse_args(argv)

    summary = run_tick(date=args.date, offline=args.offline,
                       no_llm=args.no_llm, dry_run=args.dry_run)

    mode = ("dry-run" if args.dry_run else "no-llm" if args.no_llm
            else "offline" if args.offline else "live")
    print(f"[chain_tracker] {summary['date']} {summary['tick']} ({mode}) "
          f"fetched={summary['fetched']} new={summary['new_items']} "
          f"matched={summary['matched_pairs']} llm={summary['llm_calls']} "
          f"errors={summary['llm_errors']} changes={len(summary['changes'])}")
    for c in summary["changes"]:
        print(f"  ⚡ {c['chain_name']}: {c['old_stage']} → {c['new_stage']} "
              f"({c['verdict']}) {c['summary']}")
    if summary["report_path"]:
        print(f"  报告: {summary['report_path']}")
    return 1 if summary["llm_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
