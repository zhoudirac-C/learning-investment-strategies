#!/usr/bin/env python3
"""Claims → Config 半自动桥接 CLI。

用法:
    # 扫描最近 7 天 claims，生成 entry_suggestions + 回写 linked_claims
    python scripts/sync_claims_to_config.py

    # 指定天数
    python scripts/sync_claims_to_config.py --days 3

    # 自动合并到 strategy_pack（跳过人工确认）
    python scripts/sync_claims_to_config.py --auto-merge

Refs: docs/config-cron-architecture-review.md v2.0 §4.6.2
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 添加项目 src 到路径
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "src"))

from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.tools.claims_to_entry import run_claims_to_entry_bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_claims_to_config")


def main():
    parser = argparse.ArgumentParser(
        description="Claims → Config 半自动桥接"
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="扫描最近 N 天的 claims（默认 7）"
    )
    parser.add_argument(
        "--auto-merge", action="store_true",
        help="自动合并到 strategy_pack（默认生成待确认文件）"
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="只生成预览 JSON，不写入文件（用于人工审核）"
    )
    args = parser.parse_args()

    logger.info("初始化 Neo4j 连接...")
    try:
        neo4j = Neo4jClient()
    except Exception as e:
        logger.error("Neo4j 连接失败: %s", e)
        logger.error("请确认 Neo4j 容器已启动且环境变量正确")
        sys.exit(1)

    logger.info("扫描最近 %d 天的 claims...", args.days)
    try:
        result = run_claims_to_entry_bridge(
            neo4j_client=neo4j,
            days_back=args.days,
            auto_merge=args.auto_merge,
            update_watchlist=True,
            preview_mode=args.preview,
        )
    except Exception as e:
        logger.error("桥接失败: %s", e)
        sys.exit(1)

    if result is None:
        logger.info("未发现新的介入建议。")
    elif args.preview:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.auto_merge:
        logger.info("✅ 已自动合并到 strategy_pack: %s", result)
    else:
        logger.info("✅ 已生成待确认文件: %s", result)
        print(f"\n→ 待确认文件: {result}")
        print("→ 请人工审核后复制到 strategy_pack.yaml 的 entry_points 字段")


if __name__ == "__main__":
    main()
