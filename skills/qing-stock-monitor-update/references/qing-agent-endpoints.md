# Qing-Agent 双入口差异

## 概述

Qing-Agent 提供两个分析入口，架构和数据流完全不同。

## `/analyze/trigger` — Cron 专用入口

**调用方**：`hermes_stock_monitor_agent.py`（Hermes cron）

**数据来源**：调用方提供全部数据（market_snapshot、external_sector_boards、positions、watchlist 等）。自己不拉任何数据。

**工作流**：完整 LangGraph 管线
```
parse_query → retrieve_knowledge → market_analyst → synthesize → style_writer → reviewer
```

**关键限制**：
- `market_analyst` 节点硬检查 `external_sector_boards.available`（`nodes.py:959`）
- 若 `analysis_type` 为 `"market"` 或 `"portfolio"` 且无实时数据 → **拒绝生成分析**，返回 "实时数据不可用"
- 设计意图：cron 在交易时段运行，必须基于实时数据。无数据时硬编分析对交易决策是危险的

**适用场景**：
- 交易时段大盘分析（cron 自动触发）
- 外部已准备好完整的行情+板块+持仓数据
- 需要经过 reviewer 事实核查的正式分析

**接口**：
```python
POST /analyze/trigger
Body: TriggerRequest { trigger, alerts, market_snapshot, positions, watchlist,
       sector_strengths, external_sector_boards, session_id, query }
```

## `/chat` — 用户对话入口

**调用方**：用户手动对话、Hermes 对话 session

**数据来源**：**自己拉取全部数据**：
1. Qdrant 向量检索（qing_knowledge + qing_claims）
2. Neo4j 图遍历（股票代码精准查询 + 关系发现）
3. mem0 记忆检索
4. 实时行情自动获取（指数/个股/板块/K线）
5. 持仓自动匹配（positions.yaml）

**工作流**：简化的直接 LLM 调用（**不经过** LangGraph 管线）
```
用户消息 → 查询类型检测 → 知识库检索 → 实时数据获取 → Prompt 组装 → LLM 直接输出
```

**关键特性**：
- 即使行情数据拉不到（盘后），也**不拒绝分析**——用知识库内容照样产出结果
- 数据拉取失败时静默降级：`external_sector_boards = {"available": False}`
- 不做 reviewer 事实核查

**适用场景**：
- 盘后/非交易时段的配置分析、方向判断
- 基于知识库（claims/wiki）的定性分析
- 不需要实时行情的研究型问题

**接口**：
```python
POST /chat
Body: ChatRequest { message, session_id }
```

## 选择决策树

```
需要分析什么？
├── 交易时段 cron 自动分析（含实时行情）
│   → /analyze/trigger（调用方提供数据）
│
├── 盘后配置审查、知识库分析（不需要实时行情）
│   → /chat（自己拉数据，拉不到就降级）
│
├── 单只股票深度分析（含K线+分时+持仓）
│   → /chat（自动拉取+匹配）
│
└── 快速定性判断（方向/策略基调）
    → /chat
```

## 实战陷阱（2026-06-09）

**场景**：盘后用 `/analyze/trigger` 请求 config 审查，传了 `analysis_type: "market"` 但没传 `external_sector_boards`。

**结果**：market_analyst 拒绝："实时数据不可用，拒绝生成分析"。

**正确做法**：应该用 `/chat`，消息里写明要分析的 config 内容和问题。`/chat` 即使拉不到行情数据，照样用知识库产出分析。

**教训**：盘后分析型任务永远用 `/chat`，不要用 `/analyze/trigger`。
