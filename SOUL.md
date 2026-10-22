# SOUL.md — 系统设计决策记录

> 记录项目关键架构决策及其上下文。每次重大变更后更新此文件。

---

## 2026-10-22: pinning huggingface-hub（embedding 静默失效的真机故障）

**背景**：本地 embedding 走 `transformers.AutoTokenizer` + `onnxruntime`（`src/qing_investment/agent/tools/embedding_utils.py`）。`transformers` 与 `huggingface-hub` 是传递依赖（经 `sentence-transformers`），`pyproject.toml` 从未约束过二者。

**故障**：
1. `huggingface-hub` 被升级到 **1.16.4**，而 `transformers 4.57.6` 硬性要求 `huggingface-hub>=0.34.0,<1.0`
2. 后果：`.venv/bin/python` 下 `from transformers import AutoTokenizer` **直接 ImportError** → `OnnxEmbeddingModel` 无法初始化 → **所有新起的 Python 进程 embedding 失效**（`index_claims_to_qdrant.py`、`discover_claim_relations.py`、`extract_claims_pipeline.py` 全受影响）
3. **为什么没立刻发现**：Agent 进程是在升级前启动的，内存里已加载旧 `transformers`，所以它仍能正常跑 —— 表现为「一切正常」的假象；实际只有**新进程**会暴露故障

**决策**：在 `pyproject.toml` 显式 pin 两者，杜绝传递依赖漂移
```toml
"huggingface-hub>=0.34.0,<1.0",
"transformers>=4.57,<5.0",
```
**修复动作**：`.venv/bin/pip install "huggingface-hub>=0.34.0,<1.0"` → 降级到 **0.36.2**

**验证**：
```bash
.venv/bin/python -c "
from transformers import AutoTokenizer
import sys; sys.path.insert(0,'src')
from qing_investment.agent.tools.embedding_utils import OnnxEmbeddingModel
print(OnnxEmbeddingModel().encode(['测试']).shape)   # 期望 (1, 512)
"
```

**教训（写给未来的自己）**：
- **依赖升级后必须重启所有长驻进程再验证** —— 内存里已加载的旧模块会掩盖破坏
- 排查「同一段代码在脚本里失败、在交互式里成功」时，**先比解释器与依赖版本**，别怀疑业务逻辑
- 加载失败的资源**不要缓存失败态**（本次 `_get_emb()` 曾把 ImportError 缓存为 `False`，导致语义检测层永久失效、且掩盖了真实原因）；失败应打印原始异常并允许重试
- **根因是 `uv.lock` 不是「谁装了包」** —— 项目根的 `uv.lock`（未被 git 跟踪）锁着 `huggingface-hub 1.16.4`，任何 `uv sync` 都会把破坏装回来；`pip install` 降级只是治标。已重新生成 lock（`hub 0.36.2` + `transformers 4.57.6` + `onnxruntime 1.31.0`）
- **`uv sync` 会移除「手工装但未声明」的包** —— 本次它把 `onnxruntime`（embedding 推理引擎，一直手工安装未声明）连同 `agent` extra 的一批包清掉，环境直接报废。修法：
  - `pyproject.toml` 显式声明 `onnxruntime` / `numpy`（embedding 链路）
  - 同步用 `uv sync --all-extras`（默认只装主依赖，会漏掉 `agent` extra 的 neo4j/qdrant/fastapi/uvicorn/langgraph）
  - 装完用 import 冒烟测全部关键包，别只看 pip 列表
- **uv 不读 `~/.config/pip/pip.conf`** —— 官方 pypi 会被墙，uv 需显式带镜像：
  ```bash
  export UV_INDEX_URL="http://mirrors.tencentyun.com/pypi/simple"
  export UV_TRUSTED_HOST="mirrors.tencentyun.com"
  uv lock && uv sync --all-extras --frozen
  ```
  `uv sync` 幂等性验证：再跑一次应输出 `Checked N packages` 且无增删

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
