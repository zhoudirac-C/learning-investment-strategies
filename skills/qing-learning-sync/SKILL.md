---
name: qing-learning-sync
description: |
  知识库同步管线：discover → Neo4j migrate → Qdrant → restart Agent。
  触发词：同步知识库、sync、重建索引、discover、migrate、Qdrant
---

# qing-learning-sync

## 四步强制流水线

```
① discover_claim_relations.py   →   ② migrate_claims_to_neo4j.py   →   ③ index_claims_to_qdrant.py   →   ④ 重启
    (ONNX+LLM 发现关系)                (MERGE 原子写入 Neo4j)               (向量重建，需独占锁)              (Agent+MCP)
```

**前置：Qdrant 重建前必须停 Qing-Agent + MCP server**。Neo4j 迁移不需要停。

全流程命令：

```bash
cd ~/learning-investment-strategies

# 0. 停 Qing-Agent + MCP server（释放 Qdrant .lock）
kill $(pgrep -f "mcp_qdrant_server") 2>/dev/null
kill $(pgrep -f "mcp_neo4j_server") 2>/dev/null
kill $(pgrep -f "uvicorn.*qing_investment") 2>/dev/null

# ① 关系发现（ONNX+LLM，不涉及锁）
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing

# ② Neo4j 同步（MERGE 是原子的，MVCC 安全）
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py

# ③ Qdrant 重建（需要独占锁，Step 0 已释放）
PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate

# ④ 重启 Qing-Agent
PYTHONPATH=src .venv/bin/python -m uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 --log-level info &

# ⑤ 验证 + 重启 MCP
sleep 3 && curl -s http://localhost:8000/health
hermes restart   # MCP 自动接回
```

## ~~Claims→Entry 桥接（2026-06-10 已废弃）~~

`sync_claims_to_config.py` 功能设计未落地，`entry_suggestions/` 始终为空。此步骤已从管线移除。

## 关键坑

1. **Qdrant 重建需要独占锁 —— 必须同时停 Qing-Agent + MCP server（2026-06-10 修正）**
   - Qdrant 本地模式通过 `.qdrant_data/.lock` 文件实现独占访问
   - **两个进程同时持有该锁**：Qing-Agent（uvicorn）和 MCP Qdrant server（Hermes 子进程）
   - `delete_collection()` 需要独占写锁，任一进程持有锁都会导致失败
   - 脚本内置 30 秒等待 + 强制删除兜底，但强制删除活跃进程的锁可能损坏数据
   - 正确做法：`kill $(pgrep -f "mcp_qdrant_server") && kill $(pgrep -f "uvicorn.*qing_investment")`
   - **Neo4j 迁移不需要停 Qing-Agent**：MERGE 是原子的，Neo4j 原生支持 MVCC 并发读写
2. `PYTHONUNBUFFERED=1` — 否则 cron 捕获不到 stdout
3. **仅改元数据字段**（timeframe/related_stocks/tags）→ discover 输出 0 relations 是预期的，可跳过 discover 直接 migrate
4. **改 supersedes/contradicts** → 必须跑 discover --all-missing，否则空列表覆盖 Neo4j 已有关系
5. **同步后必须验证 Agent 在线**：`curl http://localhost:8000/health`
6. **`hermes restart` 不重启 Qing-Agent（2026-06-10 发现）**：
   - `hermes restart` 只重启 Hermes 进程和 MCP server，**不负责 Qing-Agent（独立 uvicorn 进程）**
   - 同步时 Step 0 杀了 qing-agent → Qdrant 重建 → `hermes restart` **不会**把 qing-agent 带回来
   - **正确做法**：Step 4 先手动重启 qing-agent（uvicorn），Step 5/6 再 `hermes restart`
   - **反面案例**：Qdrant 重建完成后执行 `hermes restart`，以为一切正常，结果下一个 cron 又走了 fallback——因为 qing-agent 根本没被重启

## 详细文档

详见 `docs/neo4j-relation-pipeline.md`
