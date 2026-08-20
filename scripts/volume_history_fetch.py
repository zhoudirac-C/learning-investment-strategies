#!/usr/bin/env python
"""两市成交额历史回灌入口（幂等：按日期合并去重）。

用途：volume_series 块长历史段（TDX 上证+深证成指日K amount 合计）。
建议 cron：工作日 15:40 前后与 intraday_amount/sector_intraday 错峰即可（TDX 通道）。

手动: .venv/bin/python scripts/volume_history_fetch.py [--count 70]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.volume_history import compute_volume_history, save_volume_history


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="两市成交额历史回灌（TDX）")
    parser.add_argument("--count", type=int, default=70, help="回看日K根数（默认 70）")
    parser.add_argument("--out", default="infra/data/volume_history.json")
    args = parser.parse_args(argv)

    data = compute_volume_history(args.count)
    if data is None:
        print("[vh] TDX 拉取全败，不落盘", file=sys.stderr)
        return 1
    path = save_volume_history(data, Path(args.out))
    pts = data["points"]
    print(f"[vh] 两市成交额历史 → {path}  本次 {len(pts)} 根（{pts[0]['date']} ~ {pts[-1]['date']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
