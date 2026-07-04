# Qing-Agent market_analyst 拆分设计

## 问题陈述

`market_analyst` 节点单次 LLM 调用 prompt 长达 80-100KB，触发本地 Kimi Code CLI 的 `Argument list too long` 错误（Linux `execve` 参数长度限制）。

根因：该节点把"市场/板块分析"与"个股/持仓扫描"两套任务塞进同一个 prompt，导致同时注入：
- 4 个 framework 文件内容
- MACD/九转/斐波那契报告
- 板块数据与 sector_context
- 65 只 watchlist 股票的完整字段（entry_zone、risk_zone、lifecycle、watch_reason 等长文本）
- 完整持仓 JSON

历史日志显示 7月1日 `market_analyst_input: quotes=15-21 claims=0-11 positions=5-6 watchlist=65`。
当前测试样本 `tmp/agent_context_sample.json` 中，normalize 后的 65 只 watchlist  alone 即占 **44KB**。

## 目标

1. 将 `market_analyst` 拆分为职责单一的节点，单个 prompt 长度控制在本地 CLI 可承受范围（< 64KB，预留安全余量）。
2. 保持现有输出格式（`market_context`）不变，下游 `devils_advocate`/`synthesize`/`style_writer` 等节点无需感知拆分。
3. 新增充足的日志，方便观测每个节点的输入规模与耗时。
4. 提供可复用的测试样本，验证拆分前后输出等价性。

## 方案概述

将原 `market_analyst` 拆成两个顺序节点：

```text
parse_query → retrieve_knowledge → market_summary → stock_scanner
                                          ↓              ↓
                                    devils_advocate ←──┘
```

- `market_summary`：只看大盘/板块/主线，不输入完整 watchlist/positions。
- `stock_scanner`：接收 `market_summary` 输出的精简市场背景，再扫描个股/持仓，生成 `opportunity_scan` 与 `position_plans`。

## 架构变化

### 图结构变化

```text
修改前：
retrieve_knowledge → market_analyst ──┐
                     stock_analyst ──┤→ devils_advocate → ...

修改后：
retrieve_knowledge → market_summary → stock_scanner ──┐
                     stock_analyst ────────────────────┤→ devils_advocate → ...
```

`stock_analyst` 保持独立并行节点（处理单只个股查询）。

### State 变化

新增字段（均非持久化，仅本次请求内传递）：
- `market_summary_context`: `market_summary` 节点输出的精简市场背景，供 `stock_scanner` 使用。

`market_context` 仍作为最终输出字段，由 `stock_scanner` 组装：
- `market_phase`, `phase_reasoning`, `main_themes`, `sector_map`, `themes_in_focus`, `index_discipline`, `volume_note`, `emotion_signals`, `risk_notes`, `market_summary`, `citations` → 来自 `market_summary`
- `opportunity_scan`, `position_plans` → 来自 `stock_scanner`

## 节点设计

### 1. market_summary

**职责**：基于实时行情、板块数据、UP 方法论 claims，输出市场阶段、主线、板块结构、指数纪律、风险 note。

**输入 state 字段**：
- `query`
- `parsed_intent`
- `market_snapshot`（行情快照，quotes 截断到指数+重点）
- `sector_strengths`
- `external_sector_boards`
- `sector_context`
- `claims`（仅方法论相关，已过滤）
- `wiki_snippets`（仅 framework/投资方法论）
- `memories`
- `reasoning_patterns`（Top 3）
- `direction_signals`

**不输入**：
- `stock_contexts`
- `watchlist_summary`
- `reference_stocks`
- `positions`

**输出**：
```json
{
  "market_summary": "...",
  "market_phase": "...",
  "phase_reasoning": "...",
  "main_themes": [...],
  "sector_map": {...},
  "themes_in_focus": [...],
  "index_discipline": {...},
  "volume_note": "...",
  "emotion_signals": {...},
  "risk_notes": "...",
  "citations": [...]
}
```

**日志**：
- `market_summary_input: quotes=N claims=N patterns=N direction_signals=N`
- `market_summary_llm: duration=X prompt_len=N content_len=N`

### 2. stock_scanner

**职责**：在已确定的市场背景下，扫描持仓和观察池，生成机会列表与持仓操作计划。

**输入 state 字段**：
- `parsed_intent`
- `market_summary_context`（来自 market_summary 的精简输出）
- `market_snapshot`（精简版：指数+持仓+候选）
- `stock_contexts`
- `watchlist_summary`
- `reference_stocks`
- `positions`
- `direction_signals`

**输出**：完整的 `market_context`（合并 market_summary 的输出 + 个股扫描结果）
```json
{
  "market_summary": "...",
  "market_phase": "...",
  ...
  "opportunity_scan": [...],
  "position_plans": [...]
}
```

**日志**：
- `stock_scanner_input: market_summary_len=N stock_contexts=N watchlist=N positions=N`
- `stock_scanner_llm: duration=X prompt_len=N content_len=N`

## Prompt 设计

### market_summary prompt

```
{market_analyst_system_prompt 中关于大盘/板块/主线的部分}

{analysis_framework}

实时数据：
- market_snapshot: ...
- sector_strengths: ...
- external_sector_boards: ...
- sector_context: ...

知识参考：
- framework_rules: ...
- reasoning_patterns: ...
- claims: ...
- wiki_snippets: ...

请输出JSON（包含 market_summary / market_phase / phase_reasoning / main_themes / sector_map / themes_in_focus / index_discipline / volume_note / emotion_signals / risk_notes / citations）
```

### stock_scanner prompt

```
{market_analyst_system_prompt 中关于机会扫描和持仓管理的部分}

【市场背景】
{market_summary_context 的精简文本}

【需要扫描的标的】
持仓：
{positions}

观察池（按P1/P2/P3分组）：
{watchlist_summary}

非主板锚点：
{reference_stocks}

个股背景：
{stock_contexts}

方向优先级：
{direction_signals}

请输出JSON（包含 opportunity_scan / position_plans）
```

## 日志规划

除每个节点记录 `input` 与 `llm` 日志外，还需在以下位置加日志：

1. `retrieve_knowledge` 输出时记录各字段长度：
   - `quotes`, `claims`, `wiki`, `sector_context`, `stock_contexts`, `watchlist_summary`, `reference_stocks`
2. `market_summary` 记录 prompt 裁剪前后的长度。
3. `stock_scanner` 记录 `market_summary_context` 长度与最终 `market_context` 组装结果。
4. `build_graph` 输出新的拓扑结构日志。

## 测试计划

### 测试样本

已保存当前 context 样本：
- `tmp/agent_context_sample.json`（原始 fetch_json_context 输出，324KB）
- 测试脚本将模拟 `call_qing_agent` 构建 payload，并传入改造后的图。

### 回归测试

1. **输出 schema 不变**：新 `market_context` 必须包含原 `market_analyst` 的所有字段。
2. **长度下降**：`market_summary` 与 `stock_scanner` 的 prompt 长度均应 < 64KB。
3. **等价性抽查**：对相同样本，比较原 `market_analyst` 与新流程的输出关键字段（market_phase / main_themes / opportunity_scan / position_plans），语义不应冲突。

### 测试脚本

新增 `tests/test_market_analyst_split.py`：
- 读取 `tmp/agent_context_sample.json`
- 调用 `build_graph()`
- 分别调用旧函数与新图
- 对比 prompt 长度与输出字段

## 风险与回退

| 风险 | 缓解 |
|---|---|
| 下游节点依赖 `market_context.opportunity_scan` 等字段 | `stock_scanner` 输出完整 `market_context`，字段不变 |
| `market_summary` 输出不足以支撑个股扫描 | `market_summary_context` 保留 main_themes / sector_map / risk_notes / index_discipline |
| 延迟增加（多一次 LLM 调用） | 单次调用更快，总体延迟可接受；必要时 market_summary 与 stock_analyst 可并行 |
| daily_state 块生成责任变化 | market_summary 输出市场阶段 daily_state，stock_scanner 输出机会扫描 daily_state，最终合并 |

## 实施范围

修改文件：
- `src/qing_investment/agent/graph/nodes.py`：新增 `market_summary` 与 `stock_scanner`，保留原 `market_analyst` 函数一段时间便于对比。
- `src/qing_investment/agent/graph/builder.py`：更新图拓扑。
- `src/qing_investment/agent/graph/state.py`：新增 `market_summary_context` 字段。
- `src/qing_investment/agent/prompts/system/market_analyst.txt`：拆分为 `market_summary.txt` 与 `stock_scanner.txt`。
- `tests/test_market_analyst_split.py`：新增测试。

不修改：
- `stock_analyst` 节点逻辑
- `devils_advocate` / `synthesize` / `style_writer` / `reviewer` 节点
- `retrieve_knowledge` 检索逻辑
