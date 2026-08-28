#!/usr/bin/env python
"""chan 引擎历史日线回填/增量续拉 + 分钟滑动窗口快照入口（M6-1/M7-1）。

落盘：infra/data/chan_bars.db（gitignored）。幂等：同区间重跑行数不变。
默认指数集：上证/深成/创业板/沪深300；个股用 --codes 显式指定（非目标：全市场扫描）。

手动:
  .venv/bin/python scripts/fetch_chan_bars.py                          # 默认四指数全历史
  .venv/bin/python scripts/fetch_chan_bars.py --codes 600519,000001    # 加个股
  .venv/bin/python scripts/fetch_chan_bars.py --codes 600519 --start 2020-01-01 --end 2026-08-27
  .venv/bin/python scripts/fetch_chan_bars.py --incremental            # 按 coverage 末日续拉
  .venv/bin/python scripts/fetch_chan_bars.py --tf 60 --codes sh512400  # 60m 快照（新浪→TDX，260 根窗口）
  .venv/bin/python scripts/fetch_chan_bars.py --tf 30 --codes sh512400  # 30m 快照
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chan_engine.data import coverage, fetch_daily, fetch_minute, save_daily, save_minute
from chan_engine.data.fetch import VALID_MINUTE_TF, DataFetchError

DEFAULT_INDEXES = ["sh000001", "sz399001", "sz399006", "sh000300"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="chan 引擎历史日线回填/续拉 + 分钟快照")
    parser.add_argument("--codes", default=None,
                        help="逗号分隔标的（个股裸码/指数带前缀）；缺省=四指数")
    parser.add_argument("--start", default=None, help="YYYY-MM-DD（缺省=源端最早）")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD（缺省=源端最新）")
    parser.add_argument("--incremental", action="store_true",
                        help="按库内 coverage 末日续拉（首日重叠幂等）")
    parser.add_argument("--tf", type=int, default=None,
                        help="分钟周期 60/30：滑动窗口快照（新浪→TDX，忽略 start/end/incremental）")
    parser.add_argument("--db", default=None, help="自定义库路径（默认 infra/data/chan_bars.db）")
    args = parser.parse_args(argv)

    db_path = Path(args.db) if args.db else None
    codes = [c.strip() for c in args.codes.split(",")] if args.codes else list(DEFAULT_INDEXES)

    ok, failed = 0, {}
    if args.tf is not None:
        if args.tf not in VALID_MINUTE_TF:
            print(f"[chan-bars] 不支持的分钟周期 tf={args.tf}（仅 {VALID_MINUTE_TF}）")
            return 1
        for code in codes:
            try:
                rows, source = fetch_minute(code, args.tf)
            except DataFetchError as e:
                failed[code] = str(e)
                print(f"[chan-bars] {code} {args.tf}m: 失败 {e}")
                continue
            n = save_minute(code, args.tf, rows, source=source, db_path=db_path)
            ok += 1
            span = f"{rows[0]['dt']}~{rows[-1]['dt']}" if rows else "空"
            partial = sum(1 for r in rows if not r["complete"])
            print(f"[chan-bars] {code} {args.tf}m: {n} 行（{span}，源={source}，未完成bar={partial}）")
        print(f"[chan-bars] 完成 {ok}/{len(codes)}；失败 {len(failed)}")
        return 1 if failed else 0

    cov = coverage(db_path=db_path) if args.incremental else {}
    for code in codes:
        start = args.start
        if args.incremental and code in cov:
            start = cov[code][1]  # 末日起重拉（INSERT OR REPLACE 幂等）
        try:
            rows, source = fetch_daily(code, start=start, end=args.end)
        except DataFetchError as e:
            failed[code] = str(e)
            print(f"[chan-bars] {code}: 失败 {e}")
            continue
        n = save_daily(code, rows, source=source, db_path=db_path)
        ok += 1
        span = f"{rows[0]['date']}~{rows[-1]['date']}" if rows else "空"
        print(f"[chan-bars] {code}: {n} 行（{span}，源={source}）")

    print(f"[chan-bars] 完成 {ok}/{len(codes)}；失败 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
