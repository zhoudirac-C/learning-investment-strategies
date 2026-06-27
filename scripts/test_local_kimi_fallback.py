#!/usr/bin/env python3
"""测试 qing-agent LangGraph 使用本地 Kimi Code CLI + fallback 的完整流程。"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# 项目根目录
ROOT = Path("/home/ubuntu/learning-investment-strategies")
sys.path.insert(0, str(ROOT / "src"))

# 强制启用本地优先
os.environ.setdefault("KIMI_CODE_CLI_FIRST", "1")
# 给本地 CLI 一个较宽松的单次超时，避免复杂 prompt 频繁 fallback
os.environ.setdefault("KIMI_CODE_CLI_TIMEOUT", "90")

from qing_investment.agent.graph.builder import build_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_local_kimi_fallback")


def build_state(query: str) -> dict:
    return {
        "query": query,
        "session_id": "test-local-kimi",
        "trigger": {},
        "alerts": [],
        "market_snapshot": {"quotes": []},
        "positions": [],
        "watchlist": [],
        "sector_strengths": [],
        "external_sector_boards": {"available": False},
        "buy_signal_candidates": [],
        "sector_context": [],
        "claims": [],
        "wiki_snippets": [],
        "knowledge_graph": {},
        "memories": [],
        "few_shot_examples": [],
        "market_context": {},
        "stock_analysis": {},
        "draft_analysis": "",
        "styled_output": "",
        "review_notes": [],
        "final_output": "",
        "claims_cited": [],
        "data_sources": [],
        "confidence": "medium",
        "review_passed": False,
        "reasoning_steps": [],
        "parsed_intent": {},
    }


async def main() -> int:
    query = "今天大盘怎么看？"
    logger.info("=" * 60)
    logger.info("开始测试本地 Kimi Code CLI + fallback 的完整 LangGraph 流程")
    logger.info("query=%s", query)
    logger.info("KIMI_CODE_CLI_FIRST=%s", os.environ.get("KIMI_CODE_CLI_FIRST"))
    logger.info("KIMI_CODE_CLI_TIMEOUT=%s", os.environ.get("KIMI_CODE_CLI_TIMEOUT"))
    logger.info("=" * 60)

    t0 = time.time()
    graph = build_graph()
    state = build_state(query)

    try:
        result = await graph.ainvoke(state)
    except Exception as e:
        logger.exception("graph invocation failed")
        return 1

    elapsed = time.time() - t0
    logger.info("graph completed in %.1fs", elapsed)

    final = result.get("final_output", "")
    review_passed = result.get("review_passed", False)
    reasoning_steps = result.get("reasoning_steps", [])
    cost_tracking = result.get("cost_tracking", [])

    logger.info("review_passed=%s reasoning_steps=%d", review_passed, len(reasoning_steps))
    logger.info("cost_tracking entries=%d", len(cost_tracking))

    print("\n" + "=" * 60)
    print("FINAL OUTPUT")
    print("=" * 60)
    print(final or "[empty final_output]")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
