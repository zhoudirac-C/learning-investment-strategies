#!/usr/bin/env python3
"""每日开盘前热度分计算脚本。

用法:
    python scripts/calc_hot_scores.py
    
自动读取 config/stock_monitor/watchlist.yaml，
输出 config/stock_monitor/watchlist_hot_scores.json

建议 cron 配置：
    0 9 * * 1-5 cd /path/to/repo && python scripts/calc_hot_scores.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# 添加项目根目录到路径
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from qing_investment.agent.tools.hot_score import (
    calculate_all_hot_scores,
    save_hot_scores,
    load_watchlist,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting hot score calculation...")
    
    try:
        watchlist_data = load_watchlist()
        results = calculate_all_hot_scores(watchlist_data)
        save_hot_scores(results)
        
        logger.info("Hot scores calculated for %d stocks", len(results))
        logger.info("Tier summary: A=%d, B=%d, C=%d, D=%d",
            len([r for r in results if r["ranking_tier"] == "A"]),
            len([r for r in results if r["ranking_tier"] == "B"]),
            len([r for r in results if r["ranking_tier"] == "C"]),
            len([r for r in results if r["ranking_tier"] == "D"]),
        )
        
        print("\nTop 10:")
        for i, s in enumerate(results[:10], 1):
            print(f"  {i}. {s['name']}({s['code']}): {s['hot_score']} [{s['ranking_tier']}] {s['theme']}")
        
        return 0
    except Exception as e:
        logger.error("Failed to calculate hot scores: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
