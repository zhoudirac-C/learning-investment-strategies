#!/usr/bin/env python
"""东财研报/公告日更入口（v2.2 §16.4 研报管线 v1）。

cron 建议：工作日 18:10（收盘后研报/公告基本发布完；KPL 17:45 之后错开）。
落盘：infra/data/research/{reports,notices}/<YYYY-MM-DD>.json（gitignored）。
幂等：当日文件已存在则跳过，--force 重拉。

手动:
  .venv/bin/python scripts/fetch_research_reports.py                  # 今日
  .venv/bin/python scripts/fetch_research_reports.py --date 2026-08-14
  .venv/bin/python scripts/fetch_research_reports.py --start 2026-04-27 --end 2026-08-15  # 回填
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine import research_feed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="东财研报/公告日更")
    parser.add_argument("--date", default=None, help="单日 YYYY-MM-DD（默认今日）")
    parser.add_argument("--start", default=None, help="范围起点（回填用，覆盖 --date）")
    parser.add_argument("--end", default=None, help="范围终点（默认今日）")
    parser.add_argument("--root", default=str(research_feed.DEFAULT_ROOT))
    parser.add_argument("--no-notices", action="store_true", help="只拉研报不拉公告")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    today = date.today().isoformat()
    start = args.start or args.date or today
    end = args.end or (args.date if args.date and not args.start else today)
    stats = research_feed.run_range(start, end, root=Path(args.root), force=args.force,
                                    with_notices=not args.no_notices)
    n_reports = sum(v for v in stats["reports"].values())
    n_notice_days = sum(1 for v in stats["notices"].values() if isinstance(v, int))
    n_notices = sum(v for v in stats["notices"].values() if isinstance(v, int))
    errs = {d: v for d, v in stats["notices"].items() if not isinstance(v, int)}
    print(f"[research] {start}~{end}: 研报 {len(stats['reports'])} 天 {n_reports} 篇"
          f"（跳过已有 {len(stats['skipped'])} 天）; 公告 {n_notice_days} 天 {n_notices} 条")
    if errs:
        print(f"[research] 公告失败 {len(errs)} 天: {list(errs)[:5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
