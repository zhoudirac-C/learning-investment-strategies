# Qdrant 本地模式并发机制

## 核心发现（2026-06-10）

Qdrant Python client 的本地文件模式使用 **排他锁（EXCLUSIVE LOCK）**：

```python
# qdrant_client/local/qdrant_local.py 第 140-150 行
portalocker.lock(
    self._flock_file,
    portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
)
```

| 特性 | 说明 |
|------|------|
| 锁类型 | **排他锁（EXCLUSIVE）** |
| 阻塞模式 | **非阻塞（NON_BLOCKING）** |
| 含义 | **同一时刻只能有一个进程持有锁** |
| 第二个进程 | 立即抛 `RuntimeError`，不是等待 |

错误信息：
```
RuntimeError: Storage folder /path/to/.qdrant_data is already accessed by 
another instance of Qdrant client. If you require concurrent access, 
use Qdrant server instead.
```

## 底层机制

Qdrant 本地模式的数据结构：

```
.qdrant_data/
  meta.json
  .lock          ← 文件锁位置
  collection/
    qing_claims/storage.sqlite
    qing_knowledge/storage.sqlite
```

- 每个 collection 使用 SQLite 存储
- SQLite 在 WAL 模式下**支持并发读**
- 但 Qdrant 在 `.lock` 文件上加了 **EXCLUSIVE** 锁，阻止了任何并发访问

测试验证：
- EXCLUSIVE 锁会阻塞 SHARED 锁 → 第二个进程无法读取
- SHARED 锁允许多个进程同时获取 → 并发读可行

## 影响

- Qing-Agent（gunicorn worker）和 MCP Qdrant server **不能同时运行**
- 即使都是只读操作，也会冲突
- 这是 Qdrant 官方设计，不是 bug

## 解决方案

### 方案 A：停止 MCP Qdrant server（当前采用）

让 Qing-Agent 独占 Qdrant 本地文件：

```bash
# 重启 Qing-Agent 前，先停止 MCP Qdrant server
kill $(pgrep -f "mcp_qdrant_server") 2>/dev/null

# 然后启动 Qing-Agent
cd ~/learning-investment-strategies
.venv/bin/gunicorn qing_investment.agent.main:app \
  -w 1 -k uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8000 --timeout 120 --keep-alive 5
```

**优点**：
- 无需架构改动
- 立即解决锁冲突

**缺点**：
- MCP 的 Qdrant 查询功能不可用
- 需要通过 Qing-Agent API 代理查询，或错峰运行

### 方案 B：部署 Qdrant Server（未采用）

启动独立 Qdrant 服务，所有客户端通过 HTTP API 访问：

```python
# Qing-Agent 和 MCP 都改为远程模式
QdrantClient(host="localhost", port=6333)
```

**优点**：
- 真正的并发支持
- 多个客户端可同时访问

**缺点**：
- 需要运维一个额外服务
- 数据迁移（本地 `.qdrant_data` → server）
- 改动面大（Qing-Agent + MCP + 启动脚本）

### 方案 C：Monkey-patch SHARED 锁（实验成功，未采用）

将 `QdrantLocal._load()` 中的 `EXCLUSIVE` 替换为 `SHARED`：

```python
import portalocker
from qdrant_client.local.qdrant_local import QdrantLocal

original_load = QdrantLocal._load

def patched_load(self):
    # ... 原有加载逻辑 ...
    portalocker.lock(
        self._flock_file,
        portalocker.LockFlags.SHARED | portalocker.LockFlags.NON_BLOCKING,
    )

QdrantLocal._load = patched_load
```

**测试结果**：两个 `QdrantClient` 实例可以同时访问同一个本地数据库。

**风险**：
- 只读场景安全
- **写操作并发会导致数据损坏**（SQLite WAL 能处理读并发，但 Qdrant 的上层逻辑未做写协调）

**适用条件**：确认所有访问方都是只读查询（当前 MCP 和 Qing-Agent 的 `retrieve_knowledge` 都是只读）。

### 方案 D：查询代理进程（可行，未实现）

启动一个轻量级查询代理进程，通过 Unix socket 提供查询服务：

```
Qing-Agent ──► Qdrant Query Proxy ──► .qdrant_data
MCP Server ──►  (single client)    ──► (SQLite WAL)
```

**优点**：
- 单进程持有 Qdrant 连接，无锁冲突
- MCP 和 Qing-Agent 都能访问
- 不改 Qdrant 源码

**缺点**：
- 需要新增一个常驻进程
- 需要定义查询协议

## 结论

当前采用 **方案 A**：停止 MCP Qdrant server，让 Qing-Agent 独占访问。

如果未来需要恢复 MCP 的 Qdrant 查询功能，可选路径：
1. **短期**：方案 C（monkey-patch SHARED 锁），前提是确认只读
2. **长期**：方案 B（部署 Qdrant Server）或方案 D（查询代理进程）
