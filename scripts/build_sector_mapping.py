#!/usr/bin/env python3
"""定时重建个股→板块映射缓存（增量 + 重试）。

通过 cron 每半小时盘前拉取：
    */30 6-8 * * 1-5

默认增量模式：缓存未过期则跳过。
--force 强制全量重建。
--max-sectors 限制板块数量（测试用）。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 将项目根目录加入路径（用 workdir 相对路径，不依赖 __file__）
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from qing_investment.agent.tools.stock_sector_mapper import (
    build_stock_sector_mapping,
    _CACHE_FILE,
    _CACHE_TTL_SECONDS,
)


def _cache_is_fresh() -> bool:
    """检查缓存是否存在且未过期。"""
    if not _CACHE_FILE.exists():
        return False
    try:
        import json
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        ts = data.get("_built_at", 0)
        return (time.time() - ts) < _CACHE_TTL_SECONDS and len(data.get("mapping", {})) > 0
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="重建个股→板块映射缓存")
    parser.add_argument(
        "--max-sectors", type=int, default=None,
        help="限制处理的板块数量（用于测试）",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="打印每个板块的进度",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="强制全量重建，忽略已有缓存",
    )
    parser.add_argument(
        "--retries", type=int, default=3,
        help="全量构建失败时的重试次数（默认 3）",
    )
    args = parser.parse_args()

    # ── 增量模式：缓存新鲜则跳过 ──
    if not args.force and _cache_is_fresh():
        # 读取缓存统计
        import json
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        stock_count = len(data.get("mapping", {}))
        print(f"✅ 缓存未过期，跳过重建（{stock_count} 只个股）")
        return

    def _progress(current: int, total: int, name: str) -> None:
        if args.verbose or current % 10 == 0 or current == total:
            print(f"[{current:>3}/{total}] {name}")

    # ── 全量构建（带重试） ──
    last_error = None
    for attempt in range(1, args.retries + 1):
        try:
            print("=" * 50)
            print(f"开始重建个股→板块映射缓存（{'全量' if args.force else '增量过期'}, 尝试 {attempt}/{args.retries}）")
            print(f"限制: {'全部板块' if args.max_sectors is None else f'{args.max_sectors} 个板块'}")
            print("=" * 50)

            mapping = build_stock_sector_mapping(
                max_sectors=args.max_sectors,
                progress_callback=_progress,
                save_cache=args.max_sectors is None,  # 测试时不覆盖全量缓存
            )

            print("=" * 50)
            print(f"✅ 完成！覆盖 {len(mapping)} 只个股")
            print("=" * 50)
            return  # 成功就退出
        except Exception as e:
            last_error = e
            if attempt < args.retries:
                wait = 2 ** attempt * 10  # 20s, 40s, 80s 退避
                print(f"❌ 尝试 {attempt} 失败: {e}")
                print(f"   等待 {wait}s 后重试...")
                time.sleep(wait)
            else:
                print(f"❌ {args.retries} 次尝试全部失败: {e}")
                sys.exit(1)


if __name__ == "__main__":
    main()
