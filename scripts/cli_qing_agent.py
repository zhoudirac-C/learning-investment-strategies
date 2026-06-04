#!/usr/bin/env python3
"""
CLI entry point for Qing-Agent LangGraph.

Usage:
    # Simple stock question
    .venv/bin/python scripts/cli_qing_agent.py --query "分析一下中国长城"

    # Market analysis with full context from stock_monitor
    .venv/bin/python scripts/cli_qing_agent.py --query "今天大盘怎么看" --json '{"positions": [...], "watchlist": [...]}'

    # Analysis with specific stock code
    .venv/bin/python scripts/cli_qing_agent.py --query "安泰科技怎么样了" --stock-code 000969

Designed for Hermes delegate_task integration.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    """Find project root (where scripts/ and src/ live)."""
    configured = os.environ.get("HERMES_REPO_ROOT")
    if configured:
        return Path(configured)
    cwd = Path.cwd()
    if (cwd / "scripts" / "stock_monitor.py").exists():
        return cwd
    return Path(__file__).resolve().parents[1]


def _default_state(query: str, stock_code: str | None, json_input: dict | None) -> dict:
    """Build a minimal AgentState from CLI arguments.

    The graph's retrieve_knowledge node will fetch claims/wiki/memories
    on its own, so we only need to provide the query and optional context.
    """
    state: dict = {
        "query": query,
        "session_id": "cli",
        "trigger": None,
        "alerts": [],
        "positions": [],
        "watchlist": [],
        "market_snapshot": {},
        "sector_strengths": [],
        "external_sector_boards": {},
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
        "parsed_intent": {
            "stock_code": stock_code,
            "analysis_type": "stock",
            "urgency": "scheduled",
            "focus": query,
        },
    }

    if json_input:
        # Merge in context from stock_monitor JSON output
        state["positions"] = json_input.get("positions", [])
        state["watchlist"] = json_input.get("watchlist", [])
        state["market_snapshot"] = json_input.get("quote_snapshot", {})
        state["sector_strengths"] = json_input.get("sector_strengths", [])
        state["external_sector_boards"] = json_input.get("external_sector_boards", {})
        trigger = json_input.get("trigger")
        if trigger:
            state["trigger"] = trigger
        alerts = json_input.get("alerts", [])
        if alerts:
            state["alerts"] = alerts
        # If stock code wasn't explicitly passed, try to infer from context
        if not stock_code:
            for alert in alerts:
                sc = alert.get("stock_code", "")
                if sc:
                    state["parsed_intent"]["stock_code"] = sc
                    break

    return state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qing-Agent CLI — invoke LangGraph analysis graph from command line.",
    )
    parser.add_argument("--query", required=True, help="分析问题")
    parser.add_argument("--stock-code", default=None, help="股票代码（A股格式如 000969）")
    parser.add_argument(
        "--json",
        dest="json_input",
        default=None,
        help="JSON 上下文（stock_monitor --agent-json-context 的输出）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Graph invoke 超时秒数 (default: 120)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="打印调试信息到 stderr",
    )
    return parser


async def amain() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Parse optional JSON input
    json_input: dict | None = None
    if args.json_input:
        try:
            json_input = json.loads(args.json_input)
        except json.JSONDecodeError as e:
            print(f"[qing-agent CLI] 无法解析 --json 输入: {e}", file=sys.stderr)
            return 1

    # Ensure we're in the project root so imports work
    root = _repo_root()
    sys.path.insert(0, str(root / "src"))

    # Set environment defaults if not already set
    if "LLM_PROVIDER" not in os.environ:
        os.environ["LLM_PROVIDER"] = "deepseek"

    if args.verbose:
        print(f"[qing-agent CLI] root={root}", file=sys.stderr)
        print(f"[qing-agent CLI] query={args.query}", file=sys.stderr)
        print(f"[qing-agent CLI] stock_code={args.stock_code}", file=sys.stderr)
        print(f"[qing-agent CLI] json_input={'yes' if json_input else 'no'}", file=sys.stderr)

    # Build state
    state = _default_state(args.query, args.stock_code, json_input)

    # Build and invoke the graph
    try:
        from qing_investment.agent.graph.builder import build_graph

        graph = build_graph()

        if args.verbose:
            print(f"[qing-agent CLI] invoking graph (timeout={args.timeout}s)...", file=sys.stderr)

        result = await asyncio.wait_for(
            graph.ainvoke(state),
            timeout=args.timeout,
        )
    except asyncio.TimeoutError:
        print(f"[qing-agent CLI] Graph invoke 超时 ({args.timeout}s)", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[qing-agent CLI] Graph invoke 失败: {e}", file=sys.stderr)
        return 1

    # Output
    final_output = result.get("final_output", "")
    if final_output:
        print(final_output)
    else:
        # Fallback: show draft or error
        draft = result.get("draft_analysis", "")
        if draft:
            print(draft)
        else:
            print("[qing-agent] 未生成分析结果")

    if args.verbose:
        claims_cited = result.get("claims_cited", [])
        data_sources = result.get("data_sources", [])
        confidence = result.get("confidence", "N/A")
        review_passed = result.get("review_passed", False)
        steps = result.get("reasoning_steps", [])
        print(f"[qing-agent CLI] confidence={confidence}", file=sys.stderr)
        print(f"[qing-agent CLI] review_passed={review_passed}", file=sys.stderr)
        print(f"[qing-agent CLI] claims_cited={len(claims_cited)}", file=sys.stderr)
        print(f"[qing-agent CLI] data_sources={data_sources}", file=sys.stderr)
        print(f"[qing-agent CLI] reasoning_steps:", file=sys.stderr)
        for step in steps:
            print(f"  - {step}", file=sys.stderr)

    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
