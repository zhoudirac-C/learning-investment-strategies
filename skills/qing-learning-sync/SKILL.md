---
name: qing-learning-sync
description: |
  知识库同步管线：discover → Neo4j migrate → Qdrant → restart Agent。
  触发词：同步知识库、sync、重建索引、discover、migrate、Qdrant
---

# qing-learning-sync

## 四步强制流水线

```
① discover_claim_relations.py   →   ② migrate_claims_to_neo4j.py   →   ③ index_claims_to_qdrant.py   →   ④ 重启 Agent
    (ONNX+LLM 发现关系)                (增量写入 Neo4j)                     (向量重建)                       (uvicorn)
```

**步骤顺序不可跳过。** 全流程命令：

```bash
cd ~/learning-investment-strategies

# ① 关系发现
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing

# ② Neo4j 同步
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py

# ③ Qdrant 重建
PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py
# 遇到维度错误用 --force-recreate

# ④ 重启 Agent
ps aux | grep uvicorn | grep qing_investment | awk '{print $2}' | xargs kill 2>/dev/null
sleep 2
PYTHONPATH=src .venv/bin/python -m uvicorn qing_investment.agent.main:app --host 0.0.0.0 --port 8000 --log-level info &
```

## ~~Claims→Entry 桥接（2026-06-10 已废弃）~~

`sync_claims_to_config.py` 功能设计未落地，`entry_suggestions/` 始终为空。此步骤已从管线移除。

## 关键坑

1. **必须先停 Qing-Agent + MCP server**（Qdrant 本地模式独占文件锁）
   - `kill $(pgrep -f "mcp_qdrant_server")` 和 `kill $(pgrep -f "mcp_neo4j_server")` — 同步脚本的自动杀进程逻辑只针对 `uvicorn qing_investment`，不杀 Hermes 的 MCP 子进程
   - 若 MCP 死得突然，检查并清理 `.qdrant_data/.lock`
   - 同步完成后需重启 Hermes（`hermes restart`）让 MCP server 重新接入
2. `PYTHONUNBUFFERED=1` — 否则 cron 捕获不到 stdout
3. **仅改元数据字段**（timeframe/related_stocks/tags）→ discover 输出 0 relations 是预期的，可跳过 discover 直接 migrate
4. **改 supersedes/contradicts** → 必须跑 discover --all-missing，否则空列表覆盖 Neo4j 已有关系
5. **同步后必须验证 Agent 在线**：`curl http://localhost:8000/health`

## 详细文档

详见 `docs/neo4j-relation-pipeline.md`
