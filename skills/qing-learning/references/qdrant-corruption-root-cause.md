# Qdrant 本地模式向量损坏根因分析

> 2026-06-07 排查结论。触发多次（至少 2 次独立 session），修复后已集成防护。

## 错误症状

```
ValueError: could not broadcast input array from shape (512,) into shape (1,)
```

发生在 `qdrant_client/local/local_collection.py:2430`：
```python
named_vectors[idx] = vector_np  # vector_np shape=(512,), slot expects (1,)
```

## 根因链

```
Agent 运行时 QdrantClient(path=.qdrant_data) 持有 SQLite 文件锁
    ↓
索引脚本启动，另一个 QdrantClient 同时访问同一 SQLite
    ↓
并发写入竞争 → SQLite 内部向量存储某条记录维度被截断为 shape (1,)
    ↓
之后每次增量 upsert 到该坏记录 → ValueError
    ↓
删除 collection 重建 → 问题消失
```

## 为什么只发生在 claims 不发生在 documents

| 对比项 | qing_knowledge (documents) | qing_claims |
|--------|---------------------------|-------------|
| 索引方式 | 新 ID 插入 | **upsert（覆盖已有 ID 的向量）** |
| Agent 读写 | 只读 search | 只读 search |
| 损坏风险 | 低（新插入不碰旧数据） | 高（upsert 路径在并发时更容易产生 SQLite 内部不一致） |

## 为什么累积

一次并发写入产生的坏记录**永不清除**。之后的每次增量索引（`index_claims_to_qdrant.py` 默认增量模式）都会尝试 upsert 到这条坏记录 → 每次都崩溃在同一个位置（如 500/561）。只有删 collection 重建能恢复。

## 修复方案（2026-06-07 实施）

### P0: 主动防御
- `index_claims_to_qdrant.py` 和 `index_documents_to_qdrant.py` 启动前**自动 kill uvicorn Qing-Agent**
- 等待 `.qdrant_data/.lock` 释放（最多 30s）
- 两个脚本都支持 `--skip-agent-kill` 手动跳过

### P1: 一键修复
```bash
.venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate
```
自动执行：杀Agent → 等锁 → 删旧collection → 重建 → 全量索引 → 完整性自检

### P2: 完整性自检
索引用随机抽样 10 条验证向量维度=512。维度异常 → exit code=2。
监控日志写入 `logs/qdrant-index-monitor.log`（保留最近 50 条）。

### 未实施：Docker Server 模式
最彻底的修复是将 Qdrant 从本地模式迁移到 Docker Server 模式（支持真正的并发访问）。但需要启动 Docker 容器，增加运维复杂度。当前 P0+P1+P2 组合足够覆盖已知风险。
