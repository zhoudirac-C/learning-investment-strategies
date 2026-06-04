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

# 增量同步 claims 到 Neo4j（同上）
.venv/bin/python scripts/migrate_claims_to_neo4j.py
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
| `parse_query` | `graph/nodes.py:54` | ✅ | 意图解析 JSON 格式 |
| `retrieve_knowledge` | `graph/nodes.py:112` | ❌ | Neo4j/Qdrant/mem0 查询 |
| `market_analyst` | `graph/nodes.py:194` | ✅ | 板块数据可用性守卫、prompt 截断 |
| `stock_analyst` | `graph/nodes.py:261` | ✅ | 个股分析 JSON 字段 |
| `synthesize` | `graph/nodes.py:310` | ❌ | 草稿拼接规则、持仓计划注入 |
| `style_writer` | `graph/nodes.py:404` | ✅ | UP 人格 prompt、口头禅 |
| `reviewer` | `graph/nodes.py:411` | ✅ | 禁用词检测、claims 引用验证 |

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
| `market_analyst.txt` | 大盘/板块分析 JSON 输出 | 低（框架稳定） |
| `stock_analyst.txt` | 个股地位/多空证据 | 低 |
| `style_writer.txt` | UP 口吻风格化 | 中（口头禅、语气调整） |
| `reviewer.txt` | 事实核查 | 低 |

**Prompt 修改后必须测试**：市场分析的 JSON 字段是否完整、持仓计划是否生成、UP 语气是否一致。

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
│   ├── stock_analyst.txt
│   ├── style_writer.txt
│   └── reviewer.txt
└── tools/
    ├── sector_data.py      # 外部板块数据源（东财+新浪）
    ├── sector_extractor.py # 动态板块识别+网络搜索
    ├── neo4j_client.py     # Claims 图数据库
    ├── qdrant_client.py    # 文档向量检索
    ├── mem0_client.py      # 记忆层（含本地 JSON fallback）
    ├── llm_client.py       # LLM 统一封装
    └── embedding_utils.py  # embedding fallback
```

---

## 10. 设计原则（维护者必读）

1. **数据诚实 > 分析完整**：外部板块数据缺失时，宁可返回"数据不可用"也不让 LLM 编造
2. **Prompt 截断 > 全量输入**：market_snapshot.quotes 超过 50 条必须截断，控制 token
3. **幂等同步 > 全量重建**：知识库同步用脚本的增量模式，除非 `--force-full`
4. **UP 人格 > 机构腔**：style_writer 是最后一道防线，所有输出必须经过 UP 口吻过滤
