# Qing-Agent 维护指南

> 本文件面向后续维护者（包括云端 Agent 实例）。  
> 阅读前请先了解项目根目录 `AGENTS.md` 的 Required Workflow。

---

## 1. 模块定位

`qing-agent` 是 Hermes 股票监控系统的**分析大脑**，基于 LangGraph 构建有向图工作流，把原始行情、博主知识库、外部板块数据统一分析，输出 UP（青枫浦上Q）风格的投资复盘。

**核心边界**：
- 只做**分析**，不做交易执行
- 只输出**条件化的操作建议**，不给无条件买卖指令
- 外部数据不可用时**直接报错**，不虚空编造

---

## 2. 快速启动

### 2.1 依赖容器（必须提前启动）

```bash
# Neo4j（claims 图数据库）
docker run -d --name qing-neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/qingneo4j neo4j:5

# Qdrant（文档向量检索）
docker run -d --name qing-qdrant -p 6333:6333 qdrant/qdrant:v1.9.7

# Postgres（mem0 存储，可选）
docker run -d --name qing-postgres -p 5432:5432 \
  -e POSTGRES_PASSWORD=qing postgres:15
```

### 2.2 环境变量

```bash
export LLM_PROVIDER=deepseek           # 或 kimi
export DEEPSEEK_API_KEY=sk-xxx
export KIMI_API_KEY=sk-xxx             # 若使用 kimi

export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=qingneo4j

export QDRANT_HOST=localhost
export QDRANT_PORT=6333
```

### 2.3 启动服务

```bash
cd learning-investment-strategies
uv run uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000
```

健康检查：`curl http://127.0.0.1:8000/health`

---

## 3. 知识库同步（增量）

新增 raw 文档或 claim 后，**不需要全量重跑**，使用增量同步：

```bash
# 增量同步文档到 Qdrant（只处理新/修改的文件）
.venv/bin/python scripts/index_documents_to_qdrant.py

# 增量同步 claims 到 Neo4j（图关系）
.venv/bin/python scripts/migrate_claims_to_neo4j.py

# 增量同步 claims embedding 到 Qdrant（语义搜索）
.venv/bin/python scripts/index_claims_to_qdrant.py
```

**状态文件**（自动创建）：
- `.index_state.json` — Qdrant 同步状态
- `.migrate_state.json` — Neo4j 同步状态

**强制全量重跑**（数据损坏或怀疑不一致时）：
```bash
.venv/bin/python scripts/index_documents_to_qdrant.py --force-full
.venv/bin/python scripts/migrate_claims_to_neo4j.py --force-full
```

---

## 4. LangGraph 节点维护

### 4.1 节点清单

| 节点 | 文件位置 | 是否调 LLM | 维护重点 |
|------|---------|-----------|---------|
| `parse_query` | `graph/nodes.py` | ✅ | 意图解析 JSON 格式 |
| `retrieve_knowledge` | `graph/nodes.py` | ❌ | Qdrant(wiki+claims) + Neo4j + mem0 查询、来源 boost 排序、时效衰减过滤、矛盾检测 |
| `market_analyst` | `graph/nodes.py` | ✅ | 板块数据可用性守卫、framework 显式加载、动态分析框架片段注入、时效性自检 |
| `stock_analyst` | `graph/nodes.py` | ✅ | 个股分析 JSON 字段、外部标的业务校验（DuckDuckGo） |
| `synthesize` | `graph/nodes.py` | ❌ | 草稿拼接、【参考来源】注入、持仓计划注入 |
| `style_writer` | `graph/nodes.py` | ✅ | UP 人格 prompt、口头禅、强制保留来源标注 |
| `reviewer` | `graph/nodes.py` | ✅ | 禁用词检测、claims 引用验证、citation 缺失检查（最多3次打回） |

### 4.2 修改节点时的 checklist

- [ ] 修改 `AgentState`（`graph/state.py`）是否有新增字段？
- [ ] 修改 `schemas.py`（`models/schemas.py`）是否有新增 API 字段？
- [ ] 修改 prompt 后，用 `.venv/bin/python` 直接测试单个节点（见下方调试方法）
- [ ] 运行 `pytest tests/test_stock_monitor.py` 确保 Hermes 集成未破坏
- [ ] 修改后重启 uvicorn（Python 模块缓存需要重启）

---

## 5. Prompt 维护

所有 system prompt 位于 `prompts/system/`：

| Prompt | 用途 | 修改频率 |
|--------|------|---------|
| `market_analyst.txt` | 大盘/板块分析主 prompt（含 `{analysis_framework}` 占位符） | 低（方法论规则稳定） |
| `market_analysis_framework.txt` | **11 项分析框架片段**（输出格式规范） | 低（仅当 framework 输出格式变化时同步更新） |
| `stock_analyst.txt` | 个股地位/多空证据 + 外部校验指令 | 低 |
| `style_writer.txt` | UP 口吻风格化 | 中（口头禅、语气调整） |
| `reviewer.txt` | 事实核查 + citation 检查 | 低 |

**新增时效性相关维护**：
- 修改 `market_analyst.txt` 中的【时效性自检】段落时，需同步测试 Agent 是否正确标注 claim 时效
- `retrieve_knowledge` 的 `_apply_claim_freshness` 和 `_detect_claim_conflicts` 是核心过滤逻辑，修改后必须测试 claims 返回数量和排序

**Prompt 修改后必须测试**：市场分析的 JSON 字段是否完整、持仓计划是否生成、UP 语气是否一致、来源标注是否保留。

**⚠️ 关键同步规则**：`market_analysis_framework.txt` 是 Agent 输出格式的**单一来源**。当 `framework/` 目录中涉及大盘分析输出格式的文件更新时（如周期判断标准、板块映射模板变化），**必须同步检查并更新** `market_analysis_framework.txt`。

---

## 6. 板块数据源维护

### 6.1 当前双源级联

```
东方财富 API ──失败──▶ 新浪 API ──失败──▶ SectorDataUnavailableError
```

### 6.2 新增数据源的步骤

1. 在 `tools/sector_data.py` 的 `_PROVIDER_CHAIN` 中插入新 provider
2. 新 provider 函数需返回 `list[SectorBoardItem]`
3. 网络异常时抛出 `urllib.error.URLError`，由 fallback 机制捕获
4. 测试：`from qing_investment.agent.tools.sector_data import get_sector_strength_snapshot`

### 6.3 数据源失效时的行为

- `market_analyst` 检查 `external_sector_boards.available`
- 不可用时返回 `"market_phase": "数据不可用"`，拒绝生成分析
- **不要**在 prompt 中绕过此检查让 LLM 编造板块涨跌

---

## 7. 调试方法

### 7.1 单节点测试（不跑完整 graph）

```python
from qing_investment.agent.graph.nodes import market_analyst, synthesize

state = {
    "parsed_intent": {"analysis_type": "market"},
    "external_sector_boards": {"available": True, ...},
    "positions": [...],
    ...
}
result = market_analyst(state)
print(result["market_context"]["position_plans"])
```

### 7.2 完整链路测试

```bash
.venv/bin/python -c "
import asyncio
from qing_investment.agent.graph.builder import build_graph
graph = build_graph()
state = {...}
result = asyncio.run(graph.ainvoke(state))
print(result['final_output'])
"
```

### 7.3 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| `SectorDataUnavailableError` | 东财+新浪都连不上 | 检查网络，或等行情源恢复 |
| `ValueError: Provider 'kimi' requires KIMI_API_KEY` | 环境变量未设置 | `export LLM_PROVIDER=deepseek` |
| Qdrant 版本警告 | client 1.18 vs server 1.9 | 已设置 `check_compatibility=False`，可忽略 |
| LLM 返回空 | DeepSeek API 限流或超时 | 重试，或检查 API key |
| 完整链路 >60s | prompt 过大 + 多次 LLM 调用 | 已做 quotes 截断，如仍慢可考虑减少节点 |
| **索引脚本无输出/0% CPU** | ONNX Runtime 多线程 futex spin-lock 死锁（2核 VM 常见） | `sess_options.inter_op_num_threads=1; intra_op_num_threads=1` |
| **`sqlite3.OperationalError: disk I/O error`** | SQLite rollback journal 在长事务 commit 时失败 | 启用 WAL 模式（`PRAGMA journal_mode=WAL`）+ 分批 upsert（25条/批）+ 重试3次 |
| **`Storage folder already accessed`** | Qdrant 本地模式使用独占文件锁，Agent 和索引脚本不能同时打开 | **索引前必须关 Agent**，索引完重启。见下方「索引 SOP」 |

### 7.4 知识库索引 SOP

**Qdrant 本地模式限制**：只有第一个打开 `.qdrant_data/` 的进程能持有锁。Agent 启动后会持锁，因此索引脚本必须等 Agent 关闭后才能运行。

**全量重建（数据损坏/模型升级/首次部署）：**

```bash
# 1. 关 Agent
kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null

# 2. 清空旧数据 + 全量索引（预计 15-25 分钟，10,687 chunks）
cd ~/learning-investment-strategies
rm -rf .qdrant_data .index_state.json
PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_documents_to_qdrant.py

# 3. 同步 claims embedding
.venv/bin/python scripts/index_claims_to_qdrant.py

# 4. 重启 Agent
nohup .venv/bin/uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
```

**增量同步（日常新增文档后）：**

```bash
# 无需 --force-full，只处理新/修改的文件
PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_documents_to_qdrant.py
```

**关键参数**（位于 `scripts/index_documents_to_qdrant.py`）：
- `UPSERT_BATCH = 25` — 每批写入 Qdrant 的点数（太大 → SQLite I/O 错误）
- `ENCODE_BATCH = 32` — 每批 ONNX 编码的文本数（太大 → 内存爆炸 + futex 死锁）
- 单线程 ONNX（`inter_op_num_threads=1`）— 2核VM 禁用多线程，否则死锁

**预期性能**（2核/7.5GB VM，ONNX BGE-small CPU 推理）：
- 全量 10,687 chunks → 20-25 分钟
- 增量 < 100 chunks → < 30 秒

---

## 8. API 端点

### 8.1 /analyze/trigger（Hermes 调用）

```python
POST /analyze/trigger
{
  "query": "每日收盘复盘",
  "analysis_type": "market",
  "trigger": {...},
  "alerts": [...],
  "market_snapshot": {...},
  "positions": [...],
  "watchlist": [...],
  "sector_strengths": [...],
  "external_sector_boards": {"available": true, "concept": {...}, "industry": {...}}
}
```

**必填**：`query` + `external_sector_boards`（market/portfolio 分析时必须 `available=true`）

### 8.2 /chat（用户对话）

```python
POST /chat
{"message": "明天大盘怎么看", "session_id": "user-123"}
```

### 8.3 /memory/add（追加用户记忆）

```python
POST /memory/add?session_id=user-123&content=用户说今天不打算加仓&memory_type=user_decision
```

---

## 9. 文件清单

```
src/qing_investment/agent/
├── main.py                 # FastAPI 入口
├── models/schemas.py       # Pydantic 模型
├── graph/
│   ├── builder.py          # LangGraph 组装
│   ├── state.py            # AgentState TypedDict
│   ├── nodes.py            # 7 个节点实现
│   └── edges.py            # review_router
├── prompts/system/         # system prompt
│   ├── market_analyst.txt
│   ├── market_analysis_framework.txt   # 11 项分析框架片段（被 market_analyst 动态加载）
│   ├── stock_analyst.txt
│   ├── style_writer.txt
│   └── reviewer.txt
└── tools/
    ├── sector_data.py      # 外部板块数据源（东财+新浪）
    ├── sector_extractor.py # 动态板块识别+网络搜索
    ├── neo4j_client.py     # Claims 图数据库
    ├── qdrant_client.py    # 文档向量检索（REST API 兼容 Qdrant 1.9.7）
    ├── mem0_client.py      # 记忆层（含本地 JSON fallback）
    ├── llm_client.py       # LLM 统一封装 + Embedding 工厂（ONNX 优先）
    └── embedding_utils.py  # ONNX Embedding Model + Hash Fallback
```

---

## 10. 设计原则（维护者必读）

1. **数据诚实 > 分析完整**：外部板块数据缺失时，宁可返回"数据不可用"也不让 LLM 编造
2. **Prompt 截断 > 全量输入**：market_snapshot.quotes 超过 50 条必须截断，控制 token
3. **幂等同步 > 全量重建**：知识库同步用脚本的增量模式，除非 `--force-full`
4. **UP 人格 > 机构腔**：style_writer 是最后一道防线，所有输出必须经过 UP 口吻过滤
5. **来源标注 > 无据推断**：所有分析结论必须标注引用来源（claim ID / framework 文件 / wiki 路径），reviewer 会检查 citation 完整性
