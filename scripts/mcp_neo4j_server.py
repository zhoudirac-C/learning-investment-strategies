#!/usr/bin/env python3
"""
MCP Server: Neo4j Claims 图查询
───────────────────────────────
通过 stdio transport 向 Hermes Agent 暴露 Neo4j 图数据库查询能力。
连接本地 Neo4j（bolt://localhost:7687），只提供只读 Cypher 查询。

工具清单：
  get_claim_relations(claim_id)    — 查询一个 claim 的所有关系边
  search_claims_graph(keyword)     — 按关键词搜索 claims 节点
  get_recent_claims(days, type)    — 按时间和类型过滤 claims
"""

import json
import sys
import asyncio
import logging
import os
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ── 日志 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp-neo4j")

# ── Neo4j 连接（延迟初始化）───────────────────────────
_driver = None

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "qingneo4j")


def _init_neo4j():
    """初始化 Neo4j driver（单例）。"""
    global _driver
    if _driver is not None:
        return _driver

    from neo4j import GraphDatabase

    logger.info("连接 Neo4j: %s", NEO4J_URI)
    _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    # 验证连接
    _driver.verify_connectivity()
    logger.info("Neo4j 就绪")
    return _driver


def _run_query(cypher: str, **params) -> list[dict]:
    """执行只读 Cypher 查询，返回记录列表。"""
    driver = _init_neo4j()
    with driver.session(database="neo4j") as session:
        result = session.run(cypher, **params)
        return [dict(record) for record in result]


# ── 查询函数 ──────────────────────────────────────────


def _get_relations(claim_id: str) -> dict:
    """查询 claim 的关系边（supersedes/contradicts/supplements）。"""
    cypher = """
    MATCH (c:Claim {id: $id})-[r]-(other:Claim)
    RETURN c.id AS source_id,
           c.subject AS source_subject,
           type(r) AS relation,
           other.id AS target_id,
           other.subject AS target_subject,
           other.claim_type AS target_type,
           other.time_frame AS target_timeframe
    LIMIT 30
    """
    rows = _run_query(cypher, id=claim_id)

    # 按关系类型分组
    relations = {"claim_id": claim_id, "supersedes": [], "contradicts": [], "supplements": [], "other": []}
    for row in rows:
        rel_type = row["relation"].lower()
        entry = {
            "target_id": row["target_id"],
            "target_subject": row["target_subject"],
            "target_type": row["target_type"],
            "target_timeframe": row["target_timeframe"],
        }
        if rel_type in relations:
            relations[rel_type].append(entry)
        else:
            relations["other"].append(entry)

    # 如果图中没有关系边，那么该 claim 在 Neo4j 中暂无关系记录
    return relations


def _search_graph(keyword: str, limit: int = 10) -> list[dict]:
    """按关键词搜索 claims 节点。"""
    cypher = """
    MATCH (c:Claim)
    WHERE c.statement CONTAINS $keyword
       OR c.subject CONTAINS $keyword
    RETURN c.id AS id,
           c.subject AS subject,
           c.claim_type AS claim_type,
           c.time_frame AS timeframe,
           c.confidence AS confidence,
           c.source_date AS source_date,
           left(c.statement, 200) AS statement_snippet
    ORDER BY c.source_date DESC
    LIMIT $limit
    """
    return _run_query(cypher, keyword=keyword, limit=limit)


def _get_recent(days: int = 7, claim_type: str = None) -> list[dict]:
    """获取最近 N 天的 claims，可按类型过滤。"""
    from datetime import datetime, timedelta

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    if claim_type:
        cypher = """
        MATCH (c:Claim)
        WHERE c.source_date >= $cutoff AND c.claim_type = $claim_type
        RETURN c.id AS id,
               c.subject AS subject,
               c.claim_type AS claim_type,
               c.time_frame AS timeframe,
               c.confidence AS confidence,
               c.source_date AS source_date
        ORDER BY c.source_date DESC
        LIMIT 50
        """
        return _run_query(cypher, cutoff=cutoff, claim_type=claim_type)
    else:
        cypher = """
        MATCH (c:Claim)
        WHERE c.source_date >= $cutoff
        RETURN c.id AS id,
               c.subject AS subject,
               c.claim_type AS claim_type,
               c.time_frame AS timeframe,
               c.confidence AS confidence,
               c.source_date AS source_date
        ORDER BY c.source_date DESC
        LIMIT 50
        """
        return _run_query(cypher, cutoff=cutoff)


# ── MCP Server ────────────────────────────────────────
server = Server("neo4j-claims")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_claim_relations",
            description=(
                "查询 claim 关系边（supersedes取代/contradicts矛盾/supplements补充）。"
                "输入 claim ID，返回与其他 claims 的关系图谱。"
                "用于检查观点是否被取代或存在矛盾。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "Claim ID，如 claim-20260609-005-c",
                    },
                },
                "required": ["claim_id"],
            },
        ),
        Tool(
            name="search_claims_graph",
            description=(
                "在 Neo4j 精确关键词搜索 claims（匹配陈述/主题字段）。"
                "与语义搜索互补：精确关键词匹配，适合搜股票代码、板块名称。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，如'MLCC''硅片''HBM'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量，默认10",
                        "default": 10,
                    },
                },
                "required": ["keyword"],
            },
        ),
        Tool(
            name="get_recent_claims",
            description=(
                "获取最近 N 天的 claims，可按类型过滤。"
                "类型：market-cycle / sector-theme / methodology / operation / risk。"
                "适合快速了解近期市场观点和操作纪律更新。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "最近多少天，默认7",
                        "default": 7,
                    },
                    "claim_type": {
                        "type": "string",
                        "description": "可选过滤：market-cycle/sector-theme/methodology/operation/risk",
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "get_claim_relations":
            claim_id = arguments["claim_id"]
            result = _get_relations(claim_id)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "search_claims_graph":
            keyword = arguments["keyword"]
            limit = arguments.get("limit", 10)
            result = _search_graph(keyword, limit)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "get_recent_claims":
            days = arguments.get("days", 7)
            claim_type = arguments.get("claim_type")
            result = _get_recent(days, claim_type)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]

    except Exception as e:
        logger.error("工具调用失败: %s", e)
        return [TextContent(type="text", text=f"查询失败: {str(e)}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
