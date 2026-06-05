# Qing-Agent 零基础设施运行模式

> 日期: 2026-06-05 | 来源: 实战部署 + 代码审阅

## 概述

Qing-Agent（`src/qing_investment/agent/`）是基于 LangGraph 的多智能体分析系统，设计目标是让 AI 用 UP 的框架和口吻分析市场。它可以在**零 Docker 容器**的情况下运行，包括 Qdrant 本地文件模式。

## 架构

```
parse_query → retrieve_knowledge → market_analyst → stock_analyst
                                                    ↓
                                              synthesize
                                                    ↓
                                              style_writer
                                                    ↓
                                               reviewer → END
```

共 7 个节点，其中 4 个调用 LLM，3 个为纯规则处理。

## 基础设施依赖分析

| 组件 | 硬依赖 | 零容器方案 | 不可用时的行为 |
|------|--------|-----------|---------------|
| **LLM** | ✅ 必须 | API key | 整个 pipeline 的核心 |
| **Neo4j** | ❌ 可选 | 原生安装（JVM 512m-1g） | `claims = []`，静默降级 |
| **Qdrant** | ❌ 可选 | **本地文件模式 `QdrantClient(path=...)`** | `wiki_snippets = []`，静默降级 |
| **PostgreSQL** | ❌ 可选 | mem0 本地 JSON fallback | 自动降级 |
| **Docker** | ❌ 不需要 | — | 所有降级路径已实现 |

## Qdrant 本地文件模式（2026-06-05 实战验证）

### 为什么需要本地模式

- 资源受限环境（2核/3.6GB）无法跑 Docker 容器
- GitHub 下载 Qdrant binary 超时（网络限制）
- **解决方案**：`qdrant-client` Python 库内置本地文件模式，零服务器进程

### 配置步骤

**1. 添加 `qdrant_local_path` 到 config.py：**

```python
class Settings(BaseSettings):
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_local_path: str = "/path/to/.qdrant_data"  # 新增
```

**2. 重写 `QdrantClientWrapper` 支持双模式：**

```python
class QdrantClientWrapper:
    def __init__(self, local_mode: bool = True):
        if local_mode and settings.qdrant_local_path:
            self._client = QdrantClient(path=settings.qdrant_local_path)
            self._is_local = True
        else:
            self._client = QdrantClient(host=..., port=...)
            self._is_local = False
```

**3. 关键陷阱：本地模式 API 差异**

| 操作 | 远程模式 | 本地模式 |
|------|---------|---------|
| 搜索 | `client.search(collection_name=..., query_vector=...)` | `client.query_points(collection_name=..., query=...)` |
| 返回 | `list[ScoredPoint]` | `QueryResponse.points: list[ScoredPoint]` |
| 点ID | 任意字符串 | **必须是 UUID** |
| 向量格式 | 任意 | 兼容 list[float] |

**4. UUID 兼容处理：**

```python
def upsert(self, collection: str, points: list):
    if self._is_local:
        import uuid as _uuid
        for p in points:
            if not isinstance(p.id, _uuid.UUID):
                try:
                    p.id = _uuid.UUID(str(p.id))
                except ValueError:
                    p.id = _uuid.uuid5(_uuid.NAMESPACE_DNS, str(p.id))
    self._client.upsert(collection_name=collection, points=points)
```

**5. 搜索返回兼容：**

本地模式 `query_points()` 返回 `QueryResponse`（通过 `.points` 访问），远程模式 `search()` 返回 `list[ScoredPoint]`。统一转换为 dict 列表：

```python
return [
    {"id": r.id, "score": r.score, "payload": r.payload or {}}
    for r in results  # results 是 .points (本地) 或直接列表 (远程)
]
```

### 依赖安装

```bash
pip install langchain-openai onnxruntime transformers
```

- `onnxruntime`: ONNX embedding 模型运行时
- `transformers`: 模型 tokenizer
- `langchain-openai`: LLM 客户端

### Embedding 模型陷阱：`tolist()[0]` vs `tolist()`

**根因**：Fallback embedding 模型的 `.encode()` 返回的是 **numpy 1D array（shape=(512,)）**，不是 2D batch array。`.tolist()` 直接返回 `list[float]`（512个浮点数），不是 `list[list[float]]`。

```python
# ❌ 错误 — 取第一个 float，得到 0.0
embedding = emb_model.encode(text).tolist()[0]  # → 0.0

# ✅ 正确 — 直接用 tolist()
embedding = emb_model.encode(text).tolist()  # → [0.1, -0.2, ...] (512 floats)
```

**影响范围**：`index_documents_to_qdrant.py` 和 `index_claims_to_qdrant.py` 都曾有此 bug。将 `0.0`（float）作为 vector 传给 `PointStruct` 会触发 Pydantic 验证错误：
```
vector.Image: Input should be a valid dictionary or instance of Image
vector.InferenceObject: Input should be a valid dictionary or instance of InferenceObject
```

### 知识库同步脚本

```bash
# 1. Claims → Neo4j（图数据库）
.venv/bin/python scripts/migrate_claims_to_neo4j.py

# 2. 文档 → Qdrant qing_knowledge（语义检索）
.venv/bin/python scripts/index_documents_to_qdrant.py

# 3. Claims → Qdrant qing_claims（claims 语义搜索）
.venv/bin/python scripts/index_claims_to_qdrant.py
```

状态文件（`.index_state.json`, `.migrate_state.json`）自动创建，支持增量同步。删除后首次运行 = 全量重建。

### 大规模索引陷阱与修复（2026-06-05 实战）

全量重索引（557 文件 → 10,687 chunks，21 分钟）时遇到三个严重问题，按诊断顺序：

#### 陷阱 A：ONNX Runtime 多线程 futex spin-lock 死锁

**症状**：索引进度卡在 ~500 chunks，进程 0% CPU 但 RSS 极低（5MB），`strace` 显示两个线程在 `FUTEX_WAIT/FUTEX_WAKE + EAGAIN` 之间无限循环。

**根因**：ONNX Runtime `CPUExecutionProvider` 默认使用所有 CPU 核。在 2 核 VM 上，Python GIL + ONNX 工作线程争同一个 futex，触发 spin-lock 死锁。

**修复**（`embedding_utils.py`）：
```python
sess_options = ort.SessionOptions()
sess_options.inter_op_num_threads = 1
sess_options.intra_op_num_threads = 1
self.session = ort.InferenceSession(str(model_path), sess_options=sess_options, ...)
```
单线程 ONNX 推理避免了死锁，2 核 VM 上性能反而更稳定（单线程无锁竞争）。

#### 陷阱 B：SQLite rollback journal + 大事务 → disk I/O error

**症状**：索引进度卡在 ~3000 chunks，`sqlite3.OperationalError: disk I/O error` 在 commit 阶段崩溃。

**根因链**：
```
单 chunk 逐个 encode → 无 ONNX batch 加速 → 进程内存缓慢膨胀到 3.7GB
    → 大文件全部 chunk 一次 upsert → 单事务过大
    → SQLite rollback journal 在 commit 时峰值触发 → disk I/O error
```

**修复**：

1. **SQLite WAL 模式**（`qdrant_client.py`）：
   - 在 `ensure_collection()` 中、collection 创建后调用 `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL`
   - **注意时序**：`__init__` 时调用无效——此时 `storage.sqlite` 还未创建（collection 尚未存在）
   - WAL 是持久设置，一次执行后所有后续连接自动继承

2. **批量编码 + 分批 upsert**（`index_documents_to_qdrant.py`）：
   ```python
   ENCODE_BATCH = 32    # ONNX encode 一次处理 32 条文本（2核VM上限）
   UPSERT_BATCH = 25    # Qdrant upsert 一次提交 25 个 point
   MAX_RETRIES = 3      # transient I/O error 重试 + exponential backoff
   ```
   - 模型只加载一次（`get_embedding_model()` 是单例）
   - 每批 encode 后 `gc.collect()` 释放 ONNX 中间张量
   - 达到 UPSERT_BATCH 时立即 flush，避免单事务过大

3. **内存管理**：
   - 每批 upsert 后 `gc.collect()`
   - 进度输出包含 `RSS=XXMB` 实时内存监控（峰值 ~2.8GB）
   - `_upsert_with_retry()` 失败后 + `gc.collect()` + exponential backoff 重试

#### 陷阱 C：Qdrant 本地模式独占锁 → 索引脚本被 Agent 阻塞

**症状**：`RuntimeError: Storage folder .qdrant_data is already accessed by another instance`

**根因**：Qdrant 本地文件模式使用 portalocker 独占文件锁。Agent 启动时持有锁 → 索引脚本无法打开 Qdrant → 卡死（无输出、0% CPU）。

**修复（索引 SOP）**：

```bash
# 1. 关 Agent
kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null

# 2. 索引（全量 10,687 chunks 约 21 分钟）
PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_documents_to_qdrant.py

# 3. 重启 Agent
.venv/bin/uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
```

**关键点**：
- **索引前必须关 Agent**，索引完重启。无例外。
- **必须设置 `PYTHONUNBUFFERED=1`**：Hermes 进程管理捕获的 stdout 默认全缓冲，无此设置时索引跑 5 分钟不会有任何输出。
- 增量同步（新增少量文档后）同理，关 Agent → 索引 → 重启，无需 `--force-full`。

### .gitignore

```gitignore
# Qdrant local file mode data (auto-generated, 50MB+ SQLite)
.qdrant_data/
```

## 启动流程

```bash
# 1. 确认 Neo4j 运行
curl http://localhost:7474

# 2. 同步知识库（增量，首次自动全量）
.venv/bin/python scripts/migrate_claims_to_neo4j.py
.venv/bin/python scripts/index_documents_to_qdrant.py
.venv/bin/python scripts/index_claims_to_qdrant.py

# 3. 启动 Agent
.venv/bin/uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &

# 4. 验证
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"今天市场怎么样","session_id":"test"}'
```

## 资源需求（零容器 + Qdrant 本地模式）

| 资源 | 需求 | 说明 |
|------|------|------|
| CPU | 1+ 核 | Python + LangGraph |
| 内存 | ~1 GB | Python + Neo4j JVM 512m + Qdrant 本地文件 |
| 存储 | ~60 MB | Qdrant SQLite 数据文件 |
| API | LLM key | 唯一硬依赖 |

## ONNX Embedding 模型部署（2026-06-05）

### 模型来源

使用 **BGE-small-zh-v1.5**（BAAI，512维，中文优化）。在中国服务器上 HuggingFace 下载超时，改用 **ModelScope** 镜像：

```bash
pip install modelscope
python -c "
from modelscope import snapshot_download
snapshot_download('BAAI/bge-small-zh-v1.5', cache_dir='models/onnx_tmp')
"
```

### 目录结构

```
models/onnx/                      # tokenizer 文件（AutoTokenizer 从该目录加载）
├── config.json
├── tokenizer.json
├── vocab.txt
├── special_tokens_map.json
├── tokenizer_config.json
└── onnx/                         # ONNX 模型文件
    └── model_quantized.onnx       # 量化后 ~23MB（原始 ~90MB）
```

### PyTorch → ONNX 转换 + 量化

需要 torch + optimum：

```bash
pip install optimum[onnxruntime] torch --index-url https://download.pytorch.org/whl/cpu
python -c "
from optimum.onnxruntime import ORTModelForFeatureExtraction, ORTQuantizer
from optimum.onnxruntime.configuration import AutoQuantizationConfig

model = ORTModelForFeatureExtraction.from_pretrained('models/onnx_tmp/BAAI/bge-small-zh-v1___5', export=True)
model.save_pretrained('models/onnx/onnx')

quantizer = ORTQuantizer.from_pretrained('models/onnx/onnx')
dqconfig = AutoQuantizationConfig.avx512_vnni(is_static=False)
quantizer.quantize(save_dir='models/onnx/onnx_quantized', quantization_config=dqconfig)
# model_quantized.onnx → 23MB
"
```

### 验证

```bash
python -c "
from qing_investment.agent.tools.llm_client import get_embedding_model
m = get_embedding_model()  # Should print: OnnxEmbeddingModel (not FallbackEmbeddingModel)
v = m.encode('测试').tolist()
assert len(v) == 512 and sum(1 for x in v if x != 0) > 100, 'Model not working!'
print('✅ ONNX OK')
"
```

### 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| `ONNX model not found at .../model_quantized.onnx` | 模型文件缺失 | 执行上述下载+转换流程 |
| `No module named 'onnxruntime'` | 依赖缺失 | `pip install onnxruntime` |
| `No module named 'transformers'` | Tokenizer 依赖缺失 | `pip install transformers` |
| 推理极慢（0% CPU 卡死） | ONNX Runtime 多线程 futex spin-lock 死锁（2核VM） | 设置 `intra_op_num_threads=1; inter_op_num_threads=1` |
| `Storage folder already accessed` | Qdrant 本地模式独占锁，Agent 和索引脚本不能同时打开 | 索引前 `kill` Agent，索引后重启。见上方「陷阱 C」 |

## 功能对比

| 功能 | 零容器模式 | 完整 Docker 模式 |
|------|-----------|-----------------|
| LLM 市场分析 | ✅ | ✅ |
| Claims 图检索 (Neo4j) | ✅ | ✅ |
| 文档向量搜索 (Qdrant) | ✅ | ✅ |
| Claims 语义搜索 (Qdrant) | ✅ | ✅ |
| UP 风格输出 | ✅ | ✅ |
| 事实核查 | ✅ | ✅ |
| 长期记忆 (mem0) | ⚠️ JSON fallback | ✅ |
