# SOUL.md — 系统设计决策记录

> 记录项目关键架构决策及其上下文。每次重大变更后更新此文件。

---

## 2026-06-16: Qdrant 移除本地模式，仅运行服务端

**背景**：Qdrant 曾同时支持两种运行模式：
- **本地模式**（SQLite 后端）—— 通过 `QdrantClient(path=...)` 直接读写 `.qdrant_data/` 目录
- **服务端模式**（RocksDB 后端）—— 通过 `./bin/qdrant` 二进制在 port 6333 启动服务，客户端通过 HTTP 连接

**问题**：
1. **并发锁冲突**：本地模式使用 `portalocker.EXCLUSIVE` 独占文件锁，Agent 和索引脚本不能同时访问，需要串行操作
2. **SQLite 限制**：SQLite 不适合高并发写场景，大索引操作容易出现 `disk I/O error`
3. **双模式维护成本**：`QdrantClientWrapper` 需要同时维护 `query_points()` 和手动余弦相似度（`_search_manual()`）两套搜索逻辑

**决策**：彻底移除本地模式，仅保留服务端模式

**改动**：
- `src/qing_investment/agent/tools/qdrant_client.py` — 移除 `local_mode` 参数、`_is_local`、`_enable_wal_mode()`、`_search_manual()` 全部本地代码
- `src/qing_investment/agent/config.py` — 移除 `qdrant_local_path` 字段
- `scripts/mcp_qdrant_server.py`、`scripts/index_claims_to_qdrant.py`、`scripts/debug_discover.py` — 移除 `local_mode=True` 参数
- `docs/qdrant-local-to-server-migration.md` — 标记为已完成
- `src/qing_investment/agent/AGENTS.md` — 更新 Qdrant 启动和排查指引

**当前架构**：
```
┌──────────────┐     ┌──────────────┐
│  MCP Qdrant  │     │  Qing-Agent  │
│  (stdio)     │     │  (port 8000) │
│       ↓      │     │       ↓      │
│  QdrantClient│     │  QdrantClient│
│  (host:6333) │     │  (host:6333) │
└──────┬───────┘     └──────┬───────┘
       │         ✅ 并发     │
       └─────────┬──────────┘
                 ↓
       ./bin/qdrant (:6333)
            ↓
       ./storage/ (RocksDB)
```

**启动方式**：
```bash
cd /home/ubuntu/learning-investment-strategies
./bin/qdrant  # 自动使用 ./storage/ 作为数据目录
```

**验证**：`curl localhost:6333/collections`
