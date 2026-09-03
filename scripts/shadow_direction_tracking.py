#!/usr/bin/env python
"""方向层 T+5 周度跟踪入口（cron 周五盘后调用）。

聚合 evals/shadow/predictions 中已 scored 记录的 due_scores，
写 logs/direction-tracking-{today}.md 并把一行摘要打到 stdout（cron 投递用）。
手动: python scripts/shadow_direction_tracking.py [--date 2026-09-04]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from investment_engine.shadow.tracking import build_tracking, render_markdown, render_summary

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="方向层 T+5 周度跟踪")
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args(argv)

    tracking = build_tracking()
    if tracking["totals"]["dir_samples"] == 0:
        print("[skip] 无已 scored 的 prediction，退出")
        return 0
    report = LOGS_DIR / f"direction-tracking-{args.date}.md"
    report.write_text(render_markdown(tracking, today=args.date), encoding="utf-8")
    print(render_summary(tracking))
    print(f"[report] {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
