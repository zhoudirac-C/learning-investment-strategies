#!/usr/bin/env python3
"""定时重建个股→板块映射缓存。

建议通过 cron 每日开盘前运行（如 08:30）：
    0 30 8 * * 1-5 cd /path/to/repo && uv run python scripts/build_sector_mapping.py

或手动运行：
    python scripts/build_sector_mapping.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 将项目根目录加入路径
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from qing_investment.agent.tools.stock_sector_mapper import build_stock_sector_mapping


def main():
    parser = argparse.ArgumentParser(description="重建个股→板块映射缓存")
    parser.add_argument(
        "--max-sectors",
        type=int,
        default=None,
        help="限制处理的板块数量（用于测试）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="打印每个板块的进度",
    )
    args = parser.parse_args()

    def _progress(current: int, total: int, name: str) -> None:
        if args.verbose or current % 10 == 0 or current == total:
            print(f"[{current:>3}/{total}] {name}")

    print("=" * 50)
    print("开始重建个股→板块映射缓存")
    print(f"限制: {'全部' if args.max_sectors is None else args.max_sectors} 个板块")
    print("=" * 50)

    mapping = build_stock_sector_mapping(
        max_sectors=args.max_sectors,
        progress_callback=_progress,
    )

    print("=" * 50)
    print(f"完成！覆盖 {len(mapping)} 只个股")
    print("=" * 50)


if __name__ == "__main__":
    main()
