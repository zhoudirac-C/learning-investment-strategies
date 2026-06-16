#!/usr/bin/env python3
"""
MCP Server: Qdrant 语义搜索
───────────────────────────
通过 stdio transport 向 Hermes Agent 暴露 Qdrant 向量搜索能力。
启动时加载 ONNX embedding 模型（bge-small-zh-v1.5, 512-dim），
Agent 调用时实时 embed query → 搜索 → 返回结构化结果。

工具清单：
  search_claims(query, limit)   — 语义搜索投资观点 claims
  search_knowledge(query, limit) — 语义搜索 wiki/文档知识库
"""

import json
import sys
import asyncio
import logging
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ── 项目路径 ──────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# ── 日志 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,  # 只输出警告和错误，避免污染 stdio
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp-qdrant")

# ── 初始化（延迟加载，避免导入时阻塞） ────────────────
_embed_model = None
_qdrant = None
COLLECTIONS = {"qing_claims": "投资观点", "qing_knowledge": "知识文档"}


def _init_embedding():
    """加载 ONNX embedding 模型（单例）。"""
    global _embed_model
    if _embed_model is not None:
        return _embed_model

    from qing_investment.agent.tools.embedding_utils import OnnxEmbeddingModel

    logger.info("加载 ONNX embedding 模型...")
    _embed_model = OnnxEmbeddingModel()
    logger.info("ONNX embedding 模型就绪")
    return _embed_model


def _init_qdrant():
    """初始化 Qdrant 本地模式客户端（单例）。"""
    global _qdrant
    if _qdrant is not None:
        return _qdrant

    from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper

    logger.info("连接 Qdrant 服务端...")
    _qdrant = QdrantClientWrapper()
    logger.info("Qdrant 就绪")
    return _qdrant


def _search(collection: str, query: str, limit: int = 5) -> list[dict]:
    """语义搜索核心函数。"""
    embed = _init_embedding()
    qdrant = _init_qdrant()

    vec = embed.encode(query).tolist()
    results = qdrant.search(vec, collection=collection, limit=limit)

    output = []
    for r in results:
        payload = r.get("payload", {})
        item = {
            "score": round(r.get("score", 0), 4),
            "claim_id": payload.get("claim_id", ""),
            "subject": payload.get("subject", ""),
            "statement": payload.get("statement", "")[:300],
            "claim_type": payload.get("claim_type", ""),
            "confidence": payload.get("confidence", ""),
            "source_date": payload.get("source_date", ""),
        }
        output.append(item)

    return output


# ── MCP Server ────────────────────────────────────────
server = Server("qdrant-search")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_claims",
            description=(
                "语义搜索投资观点库（645条观点）。"
                "输入中文查询，返回最相关的 claims（含 ID/主题/陈述/类型/置信度/来源日期）。"
                "适合查找 UP 对某话题的方法论、板块观点、操作纪律。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "中文搜索查询，如'涨价逻辑分类''AI上游材料标的''磨底期选股方法'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量，默认5",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_knowledge",
            description=(
                "语义搜索知识文档库（10880篇知识文档）。"
                "包含 wiki、框架文档、深度研报。"
                "适合查找产业链分析、标的深度、板块扩散路径。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "中文搜索查询，如'MLCC产业链''商业航天标的''燃气轮机逻辑'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量，默认5",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "search_claims":
            query = arguments["query"]
            limit = arguments.get("limit", 5)
            results = _search("qing_claims", query, limit)
            return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, indent=2))]

        elif name == "search_knowledge":
            query = arguments["query"]
            limit = arguments.get("limit", 5)
            results = _search("qing_knowledge", query, limit)
            return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]

    except Exception as e:
        logger.error("工具调用失败: %s", e)
        return [TextContent(type="text", text=f"搜索失败: {str(e)}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
