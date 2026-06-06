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
| `retrieve_knowledge` | `graph/nodes.py` | ❌ | Qdrant(wiki+claims) + Neo4j(图遍历+关键词) + mem0 查询、来源 boost 排序、时效衰减过滤、矛盾检测 |
| `market_analyst` | `graph/nodes.py` | ✅ | 板块数据可用性守卫、framework 显式加载、**推理模式匹配（Embedding召回+LLM重排序）**、动态分析框架片段注入、时效性自检 |
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
- 修改 `market_analyst.txt` 中的【推理模式使用规则】段落时，需同步测试 `_load_reasoning_patterns()` 的匹配逻辑
- `retrieve_knowledge` 的 `_apply_claim_freshness` 和 `_detect_claim_conflicts` 是核心过滤逻辑，修改后必须测试 claims 返回数量和排序
- 推理模式匹配的核心逻辑位于 `_load_reasoning_patterns()`（Phase 6 两阶段匹配）：
  - **阶段一（Embedding召回）**：`_embed_recall_candidates()` — ONNX 计算 query 与 10 个框架的语义相似度，取 Top 5
  - **阶段二（LLM重排序）**：`_llm_rerank_patterns()` — LLM 根据候选框架的 name/description 做最终判断，返回 Top 1-3
  - **Fallback**：embedding 或 LLM 失败时，回退到多字段关键词匹配（Phase 5 逻辑）
  - 多字段索引权重：`theme=3.0`, `name=2.5`, `description=1.5`, `step_name=1.0`
  - 最低阈值：`MIN_MATCH_SCORE = 1.5`
  - 返回数量：Top 3
  - 新增 prompt 文件：`pattern_router.txt` — LLM rerank 的 system prompt

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

## 6.5 个股板块定位（三层定位法）

### 6.5.1 架构

`stock_analyst` 节点通过 `stock_sector_mapper.py` 实现**三层定位法**：

```
┌─────────────────────────────────────────┐
│  第一层：UP 知识库定位（最可靠）          │
│  - 从 claims 中提取地位关键词             │
│  - 例：龙头、中军、趋势、情绪载体、先锋    │
│  - 优点：包含产业逻辑和情绪判断           │
│  - 缺点：只覆盖 UP 提到过的个股           │
├─────────────────────────────────────────┤
│  第二层：实时板块排名定位                 │
│  - 新浪 getHQNodeData 获取板块成分股      │
│  - 按涨幅排序，计算个股排名               │
│  - 量化标签：日内龙头/前排/中军/趋势/跟风  │
├─────────────────────────────────────────┤
│  第三层：综合判断                         │
│  - UP 有标注 → 优先采用，实时数据验证      │
│  - UP 无标注 → 完全依赖量化判断            │
└─────────────────────────────────────────┘
```

### 6.5.2 数据源与降级

| 数据源 | 能力 | 状态 |
|--------|------|------|
| **新浪 getHQNodeData** | 板块成分股（涨幅/市值/换手） | ✅ 可用，有频率限制 |
| **新浪 newFLJK** | 板块列表（概念+行业，259个） | ✅ 可用 |
| **本地缓存** | 个股→板块映射（JSON） | ✅ 建立后 O(1) 查询 |

**频率限制**：新浪 `getHQNodeData` 有 IP 限流，连续请求间隔需 ≥1.5 秒。

### 6.5.3 缓存管理

**缓存文件**：`config/stock_monitor/stock_sector_mapping.json`
- 全量建立：259 个板块 → 约 6-10 分钟
- 覆盖范围：约 4300+ 只个股
- TTL：24 小时

**建立/更新**：
```bash
# 手动全量重建
.venv/bin/python scripts/build_sector_mapping.py

# 限制数量测试（仅前20个板块）
.venv/bin/python scripts/build_sector_mapping.py --max-sectors 20 --verbose

# 建议 cron（每日开盘前）
0 30 8 * * 1-5 cd /path/to/repo && uv run python scripts/build_sector_mapping.py
```

**运行时查询**：
```python
from qing_investment.agent.tools.stock_sector_mapper import get_stock_positioning, to_agent_format

result = get_stock_positioning("002892")
print(to_agent_format(result))
```

### 6.5.4 量化标签规则

| 标签 | 判定条件 | 典型场景 |
|------|---------|---------|
| **日内龙头** | 板块前3名 + 涨幅>5% | 游资点火，情绪最强 |
| **前排强势** | 板块前5名 + 涨幅>3% | 跟随龙头，有独立资金 |
| **中军/板块稳定器** | 市值>500亿 + 排名前30% + 涨幅>0% | 大票托底，机构主导 |
| **趋势/趋势容量票** | 市值>300亿 + 涨幅>0% + 换手<8% | 机构分批建仓，均线上行 |
| **跟风** | 排名后50% + 涨幅>0% | 无独立逻辑，随板块涨 |
| **弱势** | 涨幅<=0% | 跑输板块 |

### 6.5.5 维护注意

- 新浪接口被封时，`get_stock_sectors` 会降级到快速反查模式（只查最热门的 20 个板块）
- 反查模式耗时约 30-40 秒，适合应急，不适合高频调用
- 全量缓存过期后，首次查询会返回空列表，需手动重建缓存
- `stock_analyst.txt` prompt 已注入 `sector_positioning` 字段，LLM 会基于三层定位法给出地位判断

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

**知识检索策略**（2026-06-06 升级）：

| 查询类型 | Qdrant 检索 | Neo4j 检索 | 说明 |
|----------|------------|-----------|------|
| 个股查询（含6位代码） | `qing_knowledge`(wiki) + `qing_claims`(语义) | `get_claims_with_evolution(stock_code)` — 图遍历获取该股票所有 claims（含 SUPERSEDES/CONTRADICTS 关系） | 精准图查询替代模糊关键词匹配 |
| 板块/市场查询 | `qing_knowledge`(wiki) + `qing_claims`(语义) | `get_claims_by_keyword(keyword)` — 关键词匹配 | 关键词匹配 + 语义检索双保险 |
| 通用问题 | `qing_knowledge`(wiki) + `qing_claims`(语义) | 无 | 纯向量语义检索 |

**Claims 演化关系注入 Prompt**：
- 每个 claim 显示 `claim_type`（如 `[stock-view]`、`[sector-theme]`）
- 被取代的 claim 标记：`[已被 claim-xxx 取代]`
- 有矛盾的 claim 标记：`[与 claim-yyy 矛盾]`
- LLM 据此判断观点时效性和可靠性

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
│   ├── nodes.py            # 7 个节点实现（含推理模式匹配 _load_reasoning_patterns，Phase 6: Embedding+LLM rerank）
│   └── edges.py            # review_router
├── prompts/system/         # system prompt
│   ├── market_analyst.txt  # 含【推理模式使用规则】（Phase 4 新增）
│   ├── market_analysis_framework.txt   # 11 项分析框架片段（被 market_analyst 动态加载）
│   ├── pattern_router.txt  # 推理模式路由：LLM rerank 的 system prompt（Phase 6 新增）
│   ├── stock_analyst.txt
│   ├── style_writer.txt
│   └── reviewer.txt
└── tools/
    ├── sector_data.py      # 外部板块数据源（东财+新浪）
    ├── sector_extractor.py # 动态板块识别+网络搜索
    ├── neo4j_client.py     # Claims 图数据库（含图遍历查询：get_claims_with_evolution / get_related_claims）
    ├── qdrant_client.py    # 文档向量检索（REST API 兼容 Qdrant 1.9.7，支持本地模式 fallback）
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

### 架构决策：Claims 不直接提供标的列表

**决策**：Claim 中的方向推荐标的，应嵌入 `statement` 文本字段（随 Qdrant 召回自然传递），**不**通过 Neo4j 图遍历（Claim→Theme→Stock）返回。

**理由**：

| 考量 | 图遍历方案 | 文本嵌入方案 |
|------|-----------|-------------|
| 数据诚实 | ❌ 让历史 claims 充当"权威标的列表"，绕过实时数据验证 | ✅ 标的作为"UP 说过的话"呈现，保持背景参考定位 |
| 方法论过滤器 | ❌ 绕过 `_filter_methodology_only()` 有意隔离个股 claims 的设计 | ✅ 不绕过过滤器，尊重 market_analyst 只接收方法论 claims 的架构 |
| Prompt 规则 | ❌ 与"claims 仅供背景参考，不得作为当前判断依据"矛盾 | ✅ 标的跟随 claim 文本一起出现，标注为 UP 观点 |
| Schema 迁移 | ❌ 需新建 Sector→Stock 边，与 `stock_sector_mapper.py` 功能重复 | ✅ 零改动 |
| Agent 行为 | ❌ 会让 LLM 把历史推荐当买卖信号 | ✅ LLM 仍需用实时数据验证后才给建议 |

**原则**：Claims 管"UP 怎么看这个方向"，实时数据管"这个方向现在有哪些标的、涨得怎么样"。两者分工，不互相替代。

**实施**：写 claim 时，把相关标的写入 `statement` 字段（例："燃气轮机方向核心标的：杰瑞股份(002353)、中国动力(600482)..."），而非仅靠 `related_stocks` 数组。`related_stocks` 保留用于 Neo4j 实体链接，但不作为 Agent 检索路径。
