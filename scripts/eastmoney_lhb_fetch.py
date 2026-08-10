#!/usr/bin/env python
"""东财龙虎榜日榜拉取入口（cron 工作日 17:50 调用）：日榜清单 + 逐股买卖席位。

数据源见 src/investment_engine/eastmoney_lhb.py 模块docstring。
幂等：当日目标文件已存在则跳过，--force 覆盖重拉。
退出码：0 成功（含披露未出，note 如实标注）；1 拉取失败。

手动: .venv/bin/python scripts/eastmoney_lhb_fetch.py --date 2026-08-10
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine import eastmoney_lhb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="东财龙虎榜日榜拉取")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--out-root", default="infra/data/eastmoney")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.out_root) / "lhb" / f"{args.date}.json"
    if target.exists() and not args.force:
        print(f"[em-lhb] 已存在，跳过: {target}")
        return 0
    try:
        data = eastmoney_lhb.fetch_lhb(args.date)
    except eastmoney_lhb.EastmoneyError as e:
        print(f"[em-lhb] 拉取失败: {e}", file=sys.stderr)
        return 1
    path = eastmoney_lhb.save_lhb(data, Path(args.out_root), args.date)
    tail = f"（{data['note']}）" if data["note"] else ""
    print(f"[em-lhb] 龙虎榜 → {path}  上榜={data['stock_count']} 只{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
