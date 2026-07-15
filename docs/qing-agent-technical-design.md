# Qing-Agent 技术设计文档

> 版本: 2026-07-15 (v4.2)
> 对应 Commit: `34f3126` 及当前工作区
> 最后更新：watchlist 分片从外部 cron 移入 LangGraph 内部，新增 `shard_router`、`stock_scanner_shard`、`merge_scanner_results`；旧版 `v3` 已归档至 `docs/archived/qing-agent-technical-design-v3-20260612.md`

---

## 1. 概述

Qing-Agent 是 Hermes/Bridge 股票监控系统的分析大脑，负责把行情快照、持仓/观察池、外部板块数据与 UP 知识库（claims + wiki + framework）统一分析，输出 UP（青枫浦上Q）风格的投资复盘与操作建议。

核心设计原则：
- **数据诚实**：外部数据源不可用时明确降级，不让 LLM 虚空编造实时数据。
- **多源降级**：板块数据走 "东方财富/新浪传入 → 知识库 fallback" 的级联降级。
- **结构化输出**：市场分析强制 JSON，持仓计划带具体价格位与触发条件。
- **UP 人格一致性**：风格化层将专业草稿改写为 UP 口吻，语气按市场周期自适应。
- **成本可观测**：每个节点记录 LLM 调用次数与估算成本，聚合到响应中。

---

## 2. 代码目录结构

```
src/qing_investment/agent/
├── main.py                  # FastAPI 入口：/health、/analyze/trigger、/chat
├── base.py                  # Agent 基类、AgentOutput、LLMProtocol
├── config.py                # Agent 配置（LLM provider、模型名、开关等）
├── graph/
│   ├── builder.py           # LangGraph 图构建
│   ├── state.py             # AgentState TypedDict + reducer
│   ├── edges.py             # review_router 条件边
│   └── nodes.py             # 12 个图节点实现（含并行扫描分片节点）
├── agents/
│   ├── market_analyst.py    # 独立 market_analyst Agent 实现（备用）
│   ├── stock_analyst.py     # 独立 stock_analyst Agent 实现（备用）
│   └── devils_advocate.py   # Devil's Advocate 反向质疑 Agent
├── validators/
│   └── citation_validator.py# 数字/事实声明引用校验
├── prompts/system/          # 图节点 prompt 模板
│   ├── market_analyst.txt
│   ├── stock_analyst.txt
│   ├── market_analysis_framework.txt
│   ├── style_writer.txt
│   ├── reviewer.txt
│   ├── trader_mindset.txt
│   └── cron_*.txt           # 定时播报类 prompt
└── tools/                   # 工具函数与客户端
    ├── llm_client.py            # LLM/Embedding 客户端统一入口
    ├── kimi_code_cli_client.py  # 本地 Kimi Code CLI 调用封装
    ├── neo4j_client.py          # claims 图数据库
    ├── qdrant_client.py     # 向量检索
    ├── mem0_client.py       # 长期记忆
    ├── claim_freshness.py   # claims 时效性过滤
    ├── context_builder.py   # 市场上下文构建
    ├── sector_extractor.py  # 动态板块提取 + 网络新闻
    ├── stock_data.py        # 个股/指数实时数据获取
    └── cost_tracker.py      # 单次调用成本追踪
```

---

## 3. 整体架构

### 3.1 LangGraph 工作流

Qing-Agent 基于 **LangGraph** 构建有向图，共 **12 个节点 + 2 条条件边**（`shard_router` 在 `market_summary` 后 fan-out 到并行 `stock_scanner_shard`，`review_router` 在 `reviewer` 后决定是否放行或重试）。

```plantuml
@startuml
skinparam backgroundColor #FAFAFA
skinparam componentStyle rectangle
skinparam linetype ortho
skinparam defaultFontSize 13
skinparam packageBorderColor #90A4AE
skinparam packageFontColor #37474F
skinparam rectangleBorderColor #546E7A
skinparam rectangleFontColor #263238
skinparam rectangleBackgroundColor #FFFFFF
skinparam databaseBackgroundColor #FFFFFF
skinparam folderBackgroundColor #FFFFFF
skinparam noteBackgroundColor #FFFDE7
skinparam noteBorderColor #FBC02D

title Qing-Agent 架构图 v4.2 — 12 节点 LangGraph 工作流（含 watchlist 内部分片）

' ==================== 左侧：离线层 ====================
package "基础设施" #ECEFF1 {
    database "Neo4j\nclaims 图谱" as Neo4j
    database "Qdrant\n向量检索" as Qdrant
    database "Postgres\nmem0" as Postgres
}

package "知识沉淀" #ECEFF1 {
    folder "sources/raw/财经" as Raw
    folder "knowledge/claims" as Claims
    folder "knowledge/wiki" as Wiki
    folder "framework" as Framework
    folder "framework/reasoning-patterns.yaml" as ReasonPat #FFF9C4
    note right of ReasonPat
      推理模式库
      ONNX Embedding 召回 + LLM rerank
    end note
}

package "索引脚本" #ECEFF1 {
    [index_documents_to_qdrant] as IdxDoc #CFD8DC
    [migrate_claims_to_neo4j] as MigNeo #CFD8DC
    [index_claims_to_qdrant] as IdxClaims #CFD8DC
    [freshness_check] as FreshCheck #CFD8DC
}

' ==================== 中间：主流程（从上至下）====================

package "① 输入层" #E3F2FD {
    [POST /chat] as Chat
    [POST /analyze/trigger] as Trigger
    [external_sector_boards] as ESB
    [market_snapshot] as MarketSnap
    [positions] as Positions
    [watchlist] as Watchlist
}

package "② 解析层" #FFFFFF {
    [parse_query] as Parse
    note right of Parse
      graph/nodes.py
      提取 stock_code / analysis_type
    end note
}

package "③ 检索层" #F3E5F5 {
    [retrieve_knowledge] as Retrieve
    note right of Retrieve
      graph/nodes.py
      + neo4j_client.py
      + qdrant_client.py
      + mem0_client.py
      + context_builder.py
    end note

    [qing_knowledge] as QWiki
    [qing_claims] as QClaims
    [mem0] as Mem0
    [sector_extractor] as SectorExt

    [_apply_claim_freshness] as Freshness
    note right of Freshness
      ≤7天 [最新]
      8-30天 [近期]
      31-90天 [历史]
      >90天 / superseded → 过滤
    end note

    [_detect_claim_conflicts] as Conflicts
    note right of Conflicts
      同一 subject 下
      看多 vs 看空
      → potential_conflicts
    end note
}

package "④ 分析层" #E8F5E9 {
    [market_summary] as Market
    [shard_router] as ShardRouter
    [stock_scanner_shard] as ScannerShard
    [merge_scanner_results] as MergeScanner
    [stock_analyst] as Stock
    [devils_advocate] as DA

    note right of Market
      graph/nodes.py
      Framework 显式加载
      + 11项分析框架片段
      + ONNX Embedding → LLM rerank
      + 数据缺失降级
      + 输出 market_summary_context
    end note

    note right of ShardRouter
      graph/nodes.py
      按 theme / priority 拆分 watchlist
      通过 Send fan-out 到 stock_scanner_shard
    end note

    note right of ScannerShard
      graph/nodes.py
      个股扫描（分片版）
      每个 shard 只分析本批次标的
      返回 stock_scanner_results
    end note

    note right of MergeScanner
      graph/nodes.py
      合并所有 shard 的
      opportunity_scan / position_plans
      统一写入 daily_state
    end note

    note right of Stock
      graph/nodes.py
      个股地位 / 多空证据
      触发 / 失效条件
    end note

    note right of DA
      DevilsAdvocateAgent
      强制 Kimi 模型反向质疑
    end note
}

package "⑤ 生成层" #FFF8E1 {
    [synthesize] as Synth
    [style_writer] as Style
    [citation_validator] as Citation
    [reviewer] as Review

    note left of Synth
      graph/nodes.py
      纯规则拼接
      不调用 LLM
    end note

    note left of Style
      graph/nodes.py
      UP 口吻风格化
      周期自适应语气
    end note

    note left of Citation
      validators/
      citation_validator.py
      数字/事实声明
      来源覆盖率 ≥60%
    end note

    note left of Review
      graph/nodes.py
      语义审查 + 禁用词
      失败 → 打回 style_writer
      最多 3 次
    end note
}

package "⑥ 输出层" #FFF3E0 {
    [UP 风格化复盘] as Output
    note right of Output
      ① 当日定调
      ② 周期定位
      ③ 主线识别
      ④ 板块地图
      ⑤ 题材落地
      ⑥ 指数纪律
      ⑦ 量能观察
      ⑧ 情绪指标
      ⑨ 明日推演
      ⑩ 持仓计划
      ⑪ 风险提示
      + 参考来源 / 反向质疑
      + cost_info
    end note
}

' ==================== 连接线：主流程 ====================
Chat ..> Parse : 独立流程\n(不走LangGraph)
Trigger --> Parse

Parse --> Retrieve

Retrieve --> QWiki
Retrieve --> QClaims
Retrieve --> Mem0
Retrieve --> SectorExt

QClaims --> Freshness
Freshness --> Conflicts

Retrieve --> Market
Retrieve --> Stock

Market --> ShardRouter
ShardRouter --> ScannerShard : Send
ScannerShard --> MergeScanner
MergeScanner --> DA
Stock --> DA

DA --> Synth

Synth --> Style
Style --> Citation
Citation --> Review
Review --> Output : passed
Review --> Style : failed (max 3)

ESB --> Market
MarketSnap --> Market
Positions --> Market
Watchlist --> Market

' ==================== 连接线：离线层 ====================
Raw --> IdxDoc
Wiki --> IdxDoc
Framework --> IdxDoc
Claims --> MigNeo
Claims --> IdxClaims
Claims --> FreshCheck

IdxDoc --> Qdrant
MigNeo --> Neo4j
IdxClaims --> Qdrant

Qdrant --> QWiki
Qdrant --> QClaims
Neo4j --> Retrieve
Postgres --> Mem0

legend right
    | 背景色 | 层级 |
    |<#E3F2FD>| ① 输入层 |
    |<#F3E5F5>| ③ 检索层 |
    |<#E8F5E9>| ④ 分析层 |
    |<#FFF8E1>| ⑤ 生成层 |
    |<#FFF3E0>| ⑥ 输出层 |
    |<#FFEBEE>| 审核/过滤 |
    |<#ECEFF1>| 离线基础设施 |
endlegend

@enduml
```

**简化版数据流（/analyze/trigger）**：

```
parse_query
    │
    ▼
retrieve_knowledge ───────────────────┐
    │                                  │
    ▼                                  │
market_summary                        │
    │                                  │
    ▼                                  │
shard_router ──Send──▶ [stock_scanner_shard] ──▶ merge_scanner_results
    │                                  │
    ▼                                  │
devils_advocate ◄────────────────────┘
    │
    ▼
synthesize
    │
    ▼
style_writer
    │
    ▼
citation_validator
    │
    ▼
reviewer ──[pass]──▶ END
    │
  [fail]
    │
    ▼
style_writer (最多 3 次 retry)
```

**说明**：
- `retrieve_knowledge` 与 `market_summary` 每个触发只执行一次。
- `market_summary` 后由 `shard_router` 按 theme/priority 拆分 watchlist，通过 `Send` fan-out 到多个并行的 `stock_scanner_shard`。
- `merge_scanner_results` 把所有 shard 的 `opportunity_scan` / `position_plans` 合并为单一 `market_context`，并统一持久化 `daily_state`。
- `stock_analyst` 与 `merge_scanner_results` 完成后共同进入 `devils_advocate`；`stock_analyst` 仅在 `analysis_type == "stock"` 时输出有效个股分析。
- `reviewer` 失败后回写 `review_notes` 到 `style_writer`，最多重试 3 次，超过强制放行。

### 3.2 两个入口的差异

| 维度 | `POST /analyze/trigger` | `POST /chat` |
|---|---|---|
| 调用方 | Bridge/Hermes cron 任务 | 用户直接对话 |
| 是否走 LangGraph | ✅ 走完整 12 节点图（含并行 stock_scanner_shard） | ❌ 独立检索→LLM 流程 |
| 输入来源 | 结构化 `TriggerRequest`（market_snapshot、positions、watchlist、external_sector_boards 等） | 自然语言 query |
| 记忆检索 | 不查 mem0 | 查 mem0 + Neo4j 图遍历 |
| 实时数据 | 外部传入 `market_snapshot` / `external_sector_boards` | Agent 自行实时获取 |
| 写入 daily_state | ✅ `market_summary` 写市场阶段，`merge_scanner_results` 写机会/持仓计划 | ❌ 不写入 |
| 输出 | `TriggerResponse`（final_output、claims_cited、cost_info 等） | `ChatResponse`（reply） |
| 降级路径 | Qing-Agent 离线 → 纯文本 LLM fallback | 无降级，直接报错 |

---

## 4. 数据模型

### 4.1 AgentState

定义见 `src/qing_investment/agent/graph/state.py`，采用 `TypedDict` + `Annotated` reducer：

```python
class AgentState(TypedDict, total=False):
    # 输入层
    query: str
    session_id: str
    trigger: dict | None
    alerts: list[dict]
    market_snapshot: dict          # 行情快照（quotes、indices 等）
    positions: list[dict]          # 持仓列表
    watchlist: list[dict]          # 观察池
    sector_strengths: list[dict]
    external_sector_boards: dict   # 外部板块数据
    parsed_intent: dict

    # 检索层
    claims: list[dict]             # Neo4j/Qdrant 召回的 claims
    wiki_snippets: list[dict]      # Qdrant 召回的 wiki/framework
    sector_context: list[dict]
    knowledge_graph: dict
    memories: list[dict]
    few_shot_examples: list[str]
    potential_conflicts: list[dict]
    stock_contexts: list[dict]
    direction_signals: dict

    # 分片控制（v4.2 新增）
    watchlist_shard: dict | None   # 当前批次需要分析的标的子集
    shard_size: int                # watchlist 内部分片大小，0 表示不分片
    core_only: bool                # True 时只分析 priority shard（P1+持仓）
    stock_scanner_results: Annotated[list[dict], operator.add]
                                   # 并行 stock_scanner_shard 结果累加器

    # 分析层
    market_context: dict           # 最终合并后的市场/个股分析上下文
    market_summary_context: dict | None  # market_summary 输出的精简市场背景
    stock_analysis: dict           # stock_analyst JSON 输出
    devils_advocate_findings: list[dict]
    draft_analysis: str

    # 生成层
    styled_output: str
    citation_report: dict | None
    review_notes: list[str]

    # 输出层
    final_output: str
    claims_cited: list[str]
    data_sources: list[str]
    confidence: str
    review_passed: bool
    reasoning_steps: Annotated[list[str], _merge_reasoning]

    # 成本与内部控制
    cost_tracking: Annotated[list[dict], _merge_cost_tracking]
    _retry_count: int
    _data_missing_note: str
```

---

## 5. 节点详解

### 5.1 parse_query

- **位置**：`graph/nodes.py:678`
- **输入**：`query`
- **输出**：`parsed_intent`
- **逻辑**：调用 LLM 从 query 中提取 `stock_code`、`analysis_type`（stock/market/portfolio）、`urgency`、`focus`；解析失败时默认按 `analysis_type=stock` 继续。

### 5.2 retrieve_knowledge

- **位置**：`graph/nodes.py:881`
- **输入**：`query`、`parsed_intent`、`session_id`
- **输出**：`claims`、`wiki_snippets`、`memories`、`sector_context`、`stock_contexts`、`direction_signals`、`potential_conflicts`
- **数据源**：
  - **Neo4j**：个股查询用 `get_claims_with_evolution(stock_code)` 做图遍历；非个股查询用 Qdrant 召回 claim_id 后回 Neo4j 取全文。
  - **Qdrant `qing_claims`**：语义召回 claims（ONNX 512 维 embedding）。
  - **Qdrant `qing_knowledge`**：语义召回 wiki + framework + raw 文档；按来源类型 boost 排序（`framework/` > `wiki/投资方法论` > `wiki/市场分析` > `sources/raw`）。
  - **mem0**：`mem0.search(query, user_id=session_id)`。
  - **sector_extractor**：扫描 `sources/raw/财经/` 近 3 天文档，识别 Top-K 板块并补充网络新闻（仅 market/portfolio 查询）。
  - **context_builder**：为 positions/watchlist/entry_points 预构建 claims 摘要与方向信号。
- **过滤逻辑**：
  - `apply_claim_freshness`：≤7 天 [最新]、8-30 天 [近期]、31-90 天 [历史]、>90 天或 superseded 过滤。
  - `_apply_intensity_weight`：个股查询过滤 low intensity claims。
  - `_detect_claim_conflicts`：检测同一 subject 下方向相反的 claims。

### 5.3 market_summary

- **位置**：`graph/nodes.py`
- **输入**：`market_snapshot`、`external_sector_boards`、`claims`、`wiki_snippets`、`watchlist`、`positions`、`sector_context` 等
- **输出**：`market_summary_context`
- **关键逻辑**：
  1. **数据可用性守卫**：`market`/`portfolio` 分析且实时数据缺失时，注入 `_data_missing_note` 降级说明，不再拒绝分析。
  2. **行情截断**：`quotes > 50` 时只保留指数 + 持仓/观察池 + 涨跌幅 TOP15。
  3. **Framework 加载**：按 `analysis_type` 从 `framework/` 加载对应 playbook。
  4. **分析框架片段**：加载 `market_analysis_framework.txt` 中的 11 项框架替换 prompt 占位符。
  5. **推理模式匹配**：从 `framework/reasoning-patterns.yaml` 中匹配主题，ONNX Embedding 召回 Top 5 → LLM rerank Top 1-3。
  6. **Watchlist 优先级分组**：主板标的进入 `watchlist_summary`（可交易，P1-P3）；创业板/科创板（300/688）自动归为 P4-锚点，仅作情绪参考。
  7. **技术指标注入**：多级别 MACD、神奇九转、斐波那契时间分析报告。
  8. **强制 JSON 输出**，包含 `market_summary`、`market_phase`、`sector_map`、`index_discipline`、`risk_notes` 等字段。
  9. **不再直接写入个股 daily_state**：个股相关的 `opportunity_scan` / `position_plans` 留给下游 `stock_scanner_shard` → `merge_scanner_results` 统一生成并持久化。

### 5.3.1 shard_router

- **位置**：`graph/nodes.py`
- **输入**：`watchlist`、`positions`、`shard_size`、`core_only`、`watchlist_shard`
- **输出**：`list[Send]`，每个 `Send("stock_scanner_shard", {"watchlist_shard": ...})`
- **关键逻辑**：
  1. 若调用方已传入 `watchlist_shard`，直接返回单个 Send（兼容旧外部分片请求）。
  2. 否则调用 `watchlist_sharder.shard_watchlist(..., max_items=shard_size, core_only=core_only)` 生成分片。
  3. 当 `shard_size <= 0` 或 watchlist 很小时，返回单个包含全部标的的 shard，不走外部分片。
  4. 没有可分析标的时仍返回一个空 shard，保证下游节点有 `market_context`。

### 5.3.2 stock_scanner_shard

- **位置**：`graph/nodes.py`
- **输入**：`market_summary_context`、`watchlist_shard`、`market_snapshot`、`positions`、`stock_contexts`
- **输出**：`{"stock_scanner_results": [{"market_context": ..., "reasoning_steps": ..., "cost_tracking": ..., "daily_state_override": ...}]}`
- **关键逻辑**：
  1. 从 `state["watchlist_shard"]` 读取本批次标的，仅把这些 code 相关的 `watchlist_summary`、`reference_stocks`、`positions`、`stock_contexts`、`quotes` 传入 prompt。
  2. prompt 模板中的 `{shard_name}` / `{shard_items}` 替换为当前批次信息。
  3. LLM 返回 JSON，解析出 `opportunity_scan` / `position_plans`。
  4. 返回结果使用 `Annotated[list[dict], operator.add]`，多个并行节点的结果会自动累加到 `stock_scanner_results`。
  5. 提取 `daily_state` 代码块但不单独持久化，避免多并行节点写冲突。
  6. 保留 prompt 超长截断保护：超过 `_MAX_STOCK_SCANNER_PROMPT_BYTES` 时先 truncate，仍超过则返回降级结果并标记 `_truncated` / `_scan_failed`。

### 5.3.3 merge_scanner_results

- **位置**：`graph/nodes.py`
- **输入**：`stock_scanner_results`、`market_summary_context`、`trigger`、`parsed_intent`
- **输出**：`{"market_context": merged, "reasoning_steps": [...], "cost_tracking": [...], "stock_scanner_results": []}`
- **关键逻辑**：
  1. 遍历所有 shard 结果，合并 `opportunity_scan` 与 `position_plans`。
  2. 继承任意 shard 的 `_truncated` / `_scan_failed` 标记。
  3. 汇总所有 shard 的 `reasoning_steps` 与 `cost_tracking`。
  4. 调用 `_persist_daily_state_from_market_context` 统一写入 `daily_state`，source_tag 为 `stock_scanner:{analysis_type}`。
  5. 返回后清空 `stock_scanner_results`，避免旧数据影响后续触发。

### 5.4 stock_analyst

- **位置**：`graph/nodes.py:1560`
- **输入**：`parsed_intent`、`market_context`、`claims`、`wiki_snippets`
- **输出**：`stock_analysis`
- **逻辑**：个股地位判断（龙头/补涨/跟风）、多空证据、技术位置、触发/失效条件、风险点；非个股分析返回空。

### 5.5 devils_advocate

- **位置**：`graph/nodes.py`
- **输入**：`market_context`（由 `merge_scanner_results` 合并后的市场/个股上下文）、`stock_analysis`、`claims_cited`
- **输出**：`devils_advocate_findings`
- **逻辑**：实例化 `DevilsAdvocateAgent`，强制使用 Kimi 模型家族对 market + stock 结论做反向质疑；无分析内容时跳过。

### 5.6 synthesize

- **位置**：`graph/nodes.py:1830`
- **输入**：`market_context`、`stock_analysis`、`positions`、`devils_advocate_findings`
- **输出**：`draft_analysis`
- **逻辑**：纯规则拼接草稿（不调用 LLM），区分"有个股分析"和"纯市场分析"两种模板；注入持仓操作计划、反向质疑块、【参考来源】段落。

### 5.7 style_writer

- **位置**：`graph/nodes.py:1965`
- **输入**：`draft_analysis`、`market_phase`、`few_shot_examples`、`review_notes`
- **输出**：`styled_output`
- **逻辑**：加载 `style_writer.txt`，按市场周期选择语气，将专业草稿改写为 UP 口吻；注入人格特征（犀利、不劝赌、非机构腔），**不再强制使用固定口头禅**。

### 5.8 citation_validator

- **位置**：`graph/nodes.py:2010` / `validators/citation_validator.py`
- **输入**：`styled_output`
- **输出**：`citation_report`
- **逻辑**：规则引擎提取数字/事实声明，检查附近是否有来源标注；覆盖率阈值 60%，生成问题列表。**非阻断**，仅供 reviewer 参考。

### 5.9 reviewer

- **位置**：`graph/nodes.py:2075`
- **输入**：`styled_output`、`claims`、`_retry_count`
- **输出**：`review_passed`、`review_notes`、`final_output`、`_retry_count`
- **逻辑**：
  - LLM 审核禁用词、语义一致性、引用覆盖；解析失败或输出含禁用词时，使用规则兜底判定。
  - 审核未通过时，将 `_retry_count` 递增 1 写回 `AgentState`；`review_router` 据此决定回退 `style_writer` 重试，或在 `_retry_count >= 3` 时强制放行，避免无限循环。
  - 通过时 `_retry_count` 保持不变。

---

## 6. LLM 调用策略与本地降级

Qing-Agent 的图节点通过 `tools/llm_client.py` 统一调用大模型。为降低对外部 API 的依赖并复用本地 Kimi Code CLI 能力，默认采用 **本地优先、失败降级** 策略。

> **注意**：旧的 `kimi -p`（`kimi-code-cli` provider）已废弃，不再加入本地优先降级链路。当前仅保留 `kimi-code-acp`（`kimi acp`，stdio JSON-RPC）作为本地调用方式。

### 6.1 调用入口

- **统一封装**：`graph/nodes.py` 中的 `_safe_llm_invoke(prompt)` 是图节点调用 LLM 的唯一入口。
- **客户端工厂**：`tools/llm_client.py::get_llm_client(provider)` 根据 provider 名称返回对应客户端；新增 provider `kimi-code-acp` 对应本地 Kimi Code ACP。

### 6.2 本地 Kimi Code ACP 客户端

新增文件：`src/qing_investment/agent/tools/kimi_code_acp_client.py`

- **调用方式**：启动 `kimi acp` 子进程，通过 stdio JSON-RPC 与 Kimi Code CLI 交互。每次 `.invoke()` 都会新建一个 session，避免 `kimi -p` 的 argv 长度限制。
- **输出清洗**：
  - 优先从输出中提取 JSON 块；
  - 非 JSON 输出时，提取所有 `• ` 开头的 bullet 块，并去除公共缩进，保留 markdown 长文本。
- **超时控制**：默认 300 秒，可通过环境变量 `KIMI_CODE_ACP_TIMEOUT` 调整。

### 6.3 降级策略

`_safe_llm_invoke` 默认行为：

1. 若环境变量 `KIMI_CODE_ACP_FIRST` 未显式关闭（默认 `1`），先调用本地 `kimi-code-acp`。
2. 本地调用失败（ACP 不存在、异常、超时）时，记录 warning 并回退到 `settings.llm_provider`（当前默认 `deepseek`）。
3. 若 `KIMI_CODE_ACP_FIRST=0`，直接走原 provider。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `KIMI_CODE_ACP_FIRST` | `1` | 是否优先使用本地 ACP |
| `KIMI_CODE_ACP_TIMEOUT` | `300` | 本地 ACP 单次调用超时（秒） |
| `KIMI_CODE_ACP_COMMAND` | `~/.kimi-code/bin/kimi acp` | ACP 启动命令 |
| `KIMI_CODE_ACP_CWD` | 项目根目录 | ACP 子进程工作目录 |
| `KIMI_CODE_ACP_PERMISSION_MODE` | `yolo` | ACP 权限模式 |

### 6.4 注意事项

- `devils_advocate` 节点按设计仍通过 `DevilsAdvocateAgent` 直接注入 Kimi API，未接入本地 ACP 降级；当前若 Kimi API 认证失败会返回空 findings。
- 大 prompt（如 `market_summary`，约 40k token）在本地 ACP 上可能超时，会自动 fallback 到 `deepseek`。

---

## 7. 知识检索架构

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   sources/raw   │     │  framework/     │     │  knowledge/     │
│   wiki/claims   │────▶│ reasoning-      │────▶│ claims/wiki     │
└─────────────────┘     │ patterns.yaml   │     └─────────────────┘
                        └─────────────────┘              │
                                                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                         索引管线                                 │
│  index_documents_to_qdrant  │  migrate_claims_to_neo4j           │
│  index_claims_to_qdrant     │  freshness_check                   │
└─────────────────────────────────────────────────────────────────┘
                         │                    │
                         ▼                    ▼
                 ┌─────────────┐      ┌─────────────┐
                 │   Qdrant    │      │   Neo4j     │
                 │qing_knowledge      │ claims graph│
                 │qing_claims  │      │(relations)  │
                 └─────────────┘      └─────────────┘
                         │                    │
                         └────────┬───────────┘
                                  ▼
                        ┌─────────────────┐
                        │ retrieve_knowledge│
                        │  · 时效过滤       │
                        │  · 强度加权       │
                        │  · 矛盾检测       │
                        └─────────────────┘
```

---

## 8. 幻觉防御层

| 层级 | 实现 | 说明 |
|---|---|---|
| 数据源可用性 | `market_summary` 数据缺失降级 | 实时数据不可用时明确标注，基于知识库继续 |
| Claims 时效过滤 | `claim_freshness.py` | >90 天/superseded 过滤，31-90 天降权 |
| 矛盾检测 | `_detect_claim_conflicts` | 同一 subject 下方向相反 claims 告警 |
| 引用校验 | `citation_validator.py` | 数字/事实声明要求来源标注，覆盖率阈值 60% |
| 输出审核 | `reviewer` | 禁用词检测、语义审查、引用复核 |
| 反向质疑 | `DevilsAdvocateAgent` | 强制不同模型家族对结论挑错 |
| 行情截断 | `market_summary` | quotes 超 50 只时截断，减少 token 与幻觉 |

> ** reviewer 局限性**：不做数值事实核查（价格、涨跌幅正确性由 Hermes 采集层保证），不交叉验证外部新闻真实性。

---

## 9. Prompt 体系

| Prompt 文件 | 用途 | 关键占位符 |
|---|---|---|
| `market_summary.txt` | 市场/板块分析 | `{market_snapshot}`、`{analysis_framework}`、`{watchlist_summary}`、`{reasoning_patterns}` |
| `stock_scanner.txt` | 个股扫描（分片版） | `{market_summary_context}`、`{market_snapshot}`、`{positions}`、`{watchlist_summary}`、`{shard_name}`、`{shard_items}` |
| `stock_analyst.txt` | 个股地位分析 | `{stock_code}`、`{claims}`、`{market_context}` |
| `market_analysis_framework.txt` | 11 项分析框架片段 | 被替换进 `market_summary.txt` |
| `style_writer.txt` | UP 口吻风格化 | `{draft}`、`{tone}`、`{examples}` |
| `reviewer.txt` | 输出审核 | `{output}`、`{claims}` |
| `trader_mindset.txt` | 交易员心态/纪律 | 独立使用 |
| `cron_*.txt` | 定时播报（早盘/午盘/收盘/尾盘等） | 供 cron 任务直接调用 |

---

## 10. 部署与调用

### 10.1 启动

```bash
cd src
uvicorn qing_investment.agent.main:app --host 0.0.0.0 --port 8000
```

### 10.2 健康检查

```bash
curl http://localhost:8000/health
```

### 10.3 /analyze/trigger 示例

```bash
curl -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_type": "market",
    "query": "收盘复盘",
    "trigger": {"title": "收盘复盘", "reason": "收盘触发"},
    "market_snapshot": {"quotes": [...]},
    "positions": [...],
    "watchlist": [...],
    "external_sector_boards": {"available": true, "boards": [...]}
  }'
```

### 10.4 与 Bridge/Hermes 集成

- Bridge cron 通过 `scripts/hermes_stock_monitor_agent.py` 调用 Qing-Agent。
- 若 Qing-Agent 不可达，降级到 `stock_monitor.py --agent-context-on-trigger` 的纯文本 LLM 流程。

---

## 11. 成本追踪

每个 LLM 调用节点内部使用 `CostTracker` 记录：

```python
{"llm_calls": 1, "total_cost_usd": "0.0012"}
```

通过 `AgentState.cost_tracking`（`Annotated` reducer）在节点间累加，最终由 `main.py` 的 `_aggregate_cost` 汇总到 `TriggerResponse.cost_info`。

---

## 12. 变更日志

| 日期 | 变更 |
|---|---|
| 2026-06-27 | 新增本地 Kimi Code CLI 优先调用策略（`tools/kimi_code_cli_client.py`），失败/超时后 fallback 到原 API provider；修复 `reviewer` 未递增 `_retry_count` 导致的无限重试问题 |
| 2026-06-26 | v4 重写：基于真实代码更新架构图、节点说明、知识检索与幻觉防御层；移除对 UP 固定口头禅的描述 |
| 2026-06-12 | v3：新增指数多级别 K 线管线、日志系统、Watchlist P1-P4 优先级 |
| 2026-06-11 | 全量文档同步：幻觉防御层、P3 K-line、poll 字段、买入信号 |
| 2026-06-06 | 检索升级：Qdrant 语义召回 + Neo4j 图验证 + claims 时效过滤 |
