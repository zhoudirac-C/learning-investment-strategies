# Qing-Agent 盘中定时任务优化 — Implementation Plan

> 基于 `docs/qing-agent-optimization-roadmap.md` 拆分的可执行任务文档。
> 每个任务包含：目标、依赖、修改文件、具体改动、验证步骤。
> 执行顺序按阶段分组，P0 优先，P1/P2 后续。

---

## 项目约定

- 仓库根目录：`/home/ubuntu/learning-investment-strategies`
- 配置目录：`config/stock_monitor/`
- Agent 源码：`src/qing_investment/agent/`
- 监控调度：`src/qing_investment/monitor/`
- Prompt 目录：`src/qing_investment/agent/prompts/system/`
- 日志目录：`logs/`
- 所有 YAML 编辑后必须能被现有 `scripts/validate_watchlist.py` 或等价校验通过。
- 所有代码改动后必须跑通 `pytest src/qing_investment/monitor/tests/`。

---

## Phase 1：修复收盘复盘闭环（P0）

### Task 1.1：在 strategy_pack.yaml 增加 17:00 收盘复盘节点

**目标**：让调度器在每天 17:00 触发收盘复盘分析。

**依赖**：无。

**修改文件**：`config/stock_monitor/strategy_pack.yaml`

**具体改动**：
1. 在 `agent_analysis_schedule` 列表末尾追加：
   ```yaml
   - id: closing_review
     time: '17:00'
     name: 收盘复盘
     focus: 全天观点演进回顾、预判准确性评估、方向优先级重新排序、active_opportunities更新、明日核心假设与tomorrow_scenarios输出。
   ```
2. 确保 `time` 是字符串 `'17:00'`，与现有 `10:00` 格式一致。

**验证步骤**：
1. 运行 `python -c "import yaml; print(yaml.safe_load(open('config/stock_monitor/strategy_pack.yaml'))['agent_analysis_schedule'])"`，确认 `closing_review` 出现在列表中。
2. 运行 `pytest src/qing_investment/monitor/tests/` 确保配置解析测试通过。

---

### Task 1.2：让 scheduler 识别 17:00 并加载 cron_closing.txt

**目标**：当 17:00 触发时，`/analyze/trigger` 使用 `cron_closing.txt` 作为节点专属指令。

**依赖**：Task 1.1。

**修改文件**：`src/qing_investment/agent/graph/nodes.py`

**具体改动**：
1. 找到根据 trigger ID 选择 prompt 的逻辑（通常在 `market_summary` 或 `parse_query` 节点附近）。
2. 在 prompt 映射表中增加：
   ```python
   _CRON_PROMPT_MAP = {
       "open_auction": "cron_opening",
       "open_confirm": "cron_opening",  # 或独立 prompt
       "morning_confirm": "cron_morning_confirm",
       "opportunity_scan": "cron_opportunity_scan",
       "closing_review": "cron_closing",
       # ... 其他节点
   }
   ```
3. 如果当前代码没有根据 trigger ID 选择 prompt，则在 `market_summary` 节点构造 prompt 时读取 `state["trigger"]["id"]` 并映射到对应 prompt 文件。

**验证步骤**：
1. 启动本地服务 `uvicorn qing_investment.agent.main:app`。
2. 用 curl 模拟 17:00 trigger：
   ```bash
   curl -s -X POST http://127.0.0.1:8000/analyze/trigger \
     -H "Content-Type: application/json" \
     -d '{"analysis_type":"market","trigger":{"kind":"scheduled","id":"closing_review","title":"收盘复盘","reason":"收盘复盘"},"market_snapshot":{"source":"eastmoney","quotes":[]}}'
   ```
3. 检查返回的 `final_output` 是否包含"全天观点演进回顾"、"预判准确性"、"明日假设"等关键字。

---

### Task 1.3：修改 cron_closing.txt，强制读取当天 daily_state

**目标**：收盘复盘 prompt 明确要求 LLM 读取并对比当天所有节点输出。

**依赖**：Task 1.2。

**修改文件**：`src/qing_investment/agent/prompts/system/cron_closing.txt`

**具体改动**：
1. 在 prompt 开头增加：
   ```text
   【上下文输入】
   以下是你今天已经生成的 intraday_narrative 和 active_opportunities，必须在复盘中引用：
   - {intraday_narrative}
   - {active_opportunities}
   - 昨日复盘的 tomorrow_scenarios: {tomorrow_scenarios}
   ```
2. 在输出要求中增加：
   ```text
   【预判 vs 实际对比表】
   请输出一个表格，列出昨日 tomorrow_scenarios 中每个情景的预测条件、今日实际是否满足、偏差原因。
   ```
3. 将上述占位符在 `market_summary` 节点通过 `load_daily_state()` 读取并注入。

**验证步骤**：
1. 确保 `daily_state.json` 中有当天数据。
2. 触发 17:00 收盘复盘，检查返回文本是否引用了当天节点时间（如"10:00 节点认为..."）。
3. 检查返回文本是否包含"预判 vs 实际对比"。

---

### Task 1.4：daily_state 版本化写入，避免节点互相覆盖

**目标**：每个节点只更新自己负责的字段，不覆盖其他节点的输出。

**依赖**：Task 1.3。

**修改文件**：`src/qing_investment/agent/tools/daily_state.py`、`src/qing_investment/agent/graph/nodes.py`

**具体改动**：
1. 在 `daily_state.py` 中增加 `update_field(source_tag, key, value)` 函数：
   ```python
   def update_field(state: dict, source_tag: str, key: str, value: Any) -> dict:
       state.setdefault("_field_sources", {})
       state["_field_sources"][key] = source_tag
       state[key] = value
       return state
   ```
2. 在 `_persist_daily_state_from_market_context` 中使用 `update_field` 替代直接 `state["key"] = value`。
3. 对于 `intraday_narrative`，改为追加而不是覆盖：
   ```python
   state.setdefault("intraday_narrative", []).append({"time": time, "summary": summary})
   ```
4. 对于 `active_opportunities`，改为按 code 更新或追加，不直接覆盖整个列表。

**验证步骤**：
1. 手动运行 09:26、10:00 两个节点。
2. 检查 `daily_state.json` 中 `intraday_narrative` 是否同时包含两个节点的记录。
3. 检查 `_field_sources` 是否正确记录每个字段的最后一次更新来源。

---

## Phase 2：拆分股票列表，LangGraph 内部分片并行扫描（P0）

> **状态**：已实现（2026-07-15）。watchlist 分片从外部 cron 移入 Qing-Agent LangGraph 内部，外部调用方只需 POST 一次 `/analyze/trigger`。

### Task 2.1：实现 watchlist 分组逻辑

**目标**：把 watchlist 拆分为 "P1+持仓" 和 "其他按主题分组" 两组。

**依赖**：无。

**修改文件**：`src/qing_investment/agent/tools/watchlist_sharder.py`

**具体改动**：
1. 已实现 `WatchlistShard` dataclass 与 `shard_watchlist(watchlist, positions, max_items=8, core_only=False)`：
   - 支持 `watchlist` 为 `{themes: [...]}`、`{stocks: [...]}` 或列表。
   - 提取持仓代码时支持 `positions.accounts[].positions`、列表以及带 `.SH/.SZ/.BJ` 后缀的 code。
   - 返回的 shards 中第一个是 `priority`（P1 + 持仓），后续按 `theme` 分组并继续切分，保证每个 shard `len(items) <= max_items`。
2. 提供 `shard_to_context(shard)` 把 `WatchlistShard` 转成可传入 `AgentState` 的字典（只保留 `code/name/priority/theme`）。

**验证步骤**：
1. 运行 `pytest tests/test_watchlist_sharder.py -v`，确认 4 个用例通过。

---

### Task 2.2：在 AgentState / TriggerRequest 中暴露分片控制字段

**目标**：让 `/analyze/trigger` 请求可以控制分片大小与是否仅分析 priority shard。

**依赖**：无。

**修改文件**：
- `src/qing_investment/agent/graph/state.py`
- `src/qing_investment/agent/models/schemas.py`
- `src/qing_investment/agent/main.py`

**具体改动**：
1. `AgentState` 新增：
   - `shard_size: int`
   - `core_only: bool`
   - `stock_scanner_results: Annotated[list[dict], operator.add]`（并行节点结果累加器）
2. `TriggerRequest` 新增：
   - `shard_size: int = Field(default=8, ...)`，`0` 表示不分片。
   - `core_only: bool = Field(default=False, ...)`，`True` 时只分析 priority shard。
3. `analyze_trigger` 入口把 `shard_size` / `core_only` 写入初始 `AgentState`；`shard_size <= 0` 时回退为 `8`。

**验证步骤**：
1. `python -c "from qing_investment.agent.models.schemas import TriggerRequest; r=TriggerRequest(trigger={'id':'t'}); assert r.shard_size==8 and r.core_only is False"`
2. `pytest tests/test_qing_agent_monitor_workflow.py -v`

---

### Task 2.3：添加 `shard_router` 与并行扫描节点

**目标**：`market_summary` 完成后，在 LangGraph 内部把 watchlist fan-out 到多个 `stock_scanner_shard` 节点。

**依赖**：Task 2.1、Task 2.2。

**修改文件**：`src/qing_investment/agent/graph/nodes.py`、`src/qing_investment/agent/graph/builder.py`

**具体改动**：
1. 新增 `shard_router(state) -> list[Send]`：
   - 从 `state["watchlist"]` / `state["positions"]` 读取数据。
   - 若调用方已传入 `state["watchlist_shard"]`，直接返回单个 Send（兼容旧外部分片请求）。
   - 否则调用 `shard_watchlist(..., max_items=state["shard_size"], core_only=state["core_only"])`。
   - 当 `shard_size <= 0` 或 watchlist 很小时，返回单个包含全部标的的 shard。
2. 将原 `stock_scanner` 改名为 `stock_scanner_shard`：
   - 保留原有 prompt 构造、LLM 调用、JSON 解析逻辑。
   - 若 `state["watchlist_shard"]` 存在，则只把该 shard 的标的上下文传入 prompt。
   - 返回形状改为 `{"stock_scanner_results": [{"market_context": ..., "reasoning_steps": ..., "cost_tracking": ..., "daily_state_override": ...}]}`，适配 `Annotated[list[dict], operator.add]`。
   - 移除函数内部的 bisect 二分 fallback（graph 级 fan-out 已处理）。
   - 移除函数内对 `_persist_daily_state_from_market_context` 的调用，改为在 `merge_scanner_results` 统一持久化。
3. 在 `builder.py` 中：
   - 注册 `stock_scanner_shard`、`merge_scanner_results`。
   - `market_summary` 后接 `builder.add_conditional_edges("market_summary", shard_router, ["stock_scanner_shard"])`。
   - `stock_scanner_shard` → `merge_scanner_results` → `devils_advocate`。

**验证步骤**：
1. `pytest tests/test_shard_router.py -v`
2. `python -c "from qing_investment.agent.graph.builder import build_graph; g=build_graph(); print(list(g.nodes))"`，确认包含 `shard_router`、`stock_scanner_shard`、`merge_scanner_results`，无 `stock_scanner`。

---

### Task 2.4：添加 `merge_scanner_results` 合并节点

**目标**：把多个 `stock_scanner_shard` 的输出合并为单一 `market_context`，并只写一次 `daily_state`。

**依赖**：Task 2.3。

**修改文件**：`src/qing_investment/agent/graph/nodes.py`

**具体改动**：
1. 新增 `merge_scanner_results(state) -> AgentState`：
   - 读取 `state["stock_scanner_results"]`，把每个结果的 `market_context.opportunity_scan` / `position_plans` 追加到合并后的 `market_context`。
   - 任意 shard 标记了 `_truncated` / `_scan_failed` 时，合并结果也继承该标记。
   - 汇总所有 shard 的 `reasoning_steps` 与 `cost_tracking`。
   - 调用 `_persist_daily_state_from_market_context(merged, None, source_tag, trigger_id)` 统一持久化。
   - 返回 `{"market_context": merged, "reasoning_steps": [...], "cost_tracking": [...], "stock_scanner_results": []}`。

**验证步骤**：
1. `pytest tests/test_merge_scanner_results.py -v`
2. `pytest tests/test_qing_agent_monitor_workflow.py::test_qing_agent_internal_sharding -v`

---

### Task 2.5：简化外部 cron 脚本

**目标**：`scripts/hermes_stock_monitor_agent.py` 不再做外部分片、聚合与多次 `/analyze/trigger` 调用。

**依赖**：Task 2.2。

**修改文件**：`scripts/hermes_stock_monitor_agent.py`

**具体改动**：
1. 删除 `watchlist_sharder` import、`SHARDABLE_TRIGGER_IDS`、`WATCHLIST_SHARD_SIZE`、`WATCHLIST_CORE_ONLY`、`_aggregate_sharded_responses`。
2. `call_qing_agent` 构造 payload 时直接传入：
   - `"shard_size": int(os.environ.get("WATCHLIST_SHARD_SIZE", "8"))`
   - `"core_only": os.environ.get("WATCHLIST_CORE_ONLY", "0").lower() in ("1", "true", "yes", "on")`
3. 仅调用一次 `_post_analyze_trigger(payload)`。

**验证步骤**：
1. `python -c "import sys; sys.path.insert(0,'src'); from scripts.hermes_stock_monitor_agent import call_qing_agent; print('import OK')"`
2. 在 dry-run 或 mock quotes 环境下跑一次 cron，确认日志中只有单次 `/analyze/trigger` POST。

---

## Phase 3：修复 citation / 参考来源机制（P0）

### Task 3.1：claims 输入格式改为 claim ID 前置

**目标**：让 LLM 在生成时能直接看到并引用 claim ID。

**依赖**：无。

**修改文件**：`src/qing_investment/agent/main.py` 或 `src/qing_investment/agent/graph/nodes.py`

**具体改动**：
1. 找到 format claims 的函数（如 `_format_claim_line`）。
2. 改为：
   ```python
   def _format_claim_line(c: dict) -> str:
       claim_id = c.get('id', 'N/A')
       parts = [f"[{claim_id}]"]
       parts.append(f" ({c.get('source_date','')})")
       if c.get('claim_type'):
           parts.append(f" [{c.get('claim_type')}]")
       parts.append(f": {c.get('statement', '')[:200]}")
       return "".join(parts)
   ```

**验证步骤**：
1. 触发一次分析，检查日志中 `market_summary_input: claims=N` 之后的 prompt 片段是否以 `[claim-xxx]` 开头。
2. 确认 citation_validator 统计的 `cited` 数量从 0 开始提升。

---

### Task 3.2：在 style_writer prompt 注入 citation 要求

**目标**：让 style_writer 生成输出时就带有引用，而不是事后校验。

**依赖**：Task 3.1。

**修改文件**：`src/qing_investment/agent/prompts/system/style_writer.txt`

**具体改动**：
1. 在 prompt 中增加：
   ```text
   【引用规范】
   - 所有引用 UP 方法论概念、历史观点或具体 claim 的句子，必须在句末标注来源，格式为 [claim-xxx]。
   - 行情数据（指数、涨跌幅、成交量）默认来自实时快照，无需逐条引用。
   - 不要编造 claim ID；如果无法确定来源，使用 [未找到来源]。
   ```

**验证步骤**：
1. 触发分析，检查 `final_output` 是否包含 `[claim-xxx]`。
2. 检查 reviewer 是否不再因为"缺少参考来源"而失败。

---

### Task 3.3：简化 reviewer 的 citation 检查规则

**目标**：避免 reviewer 对行情数据过度敏感。

**依赖**：Task 3.2。

**修改文件**：`src/qing_investment/agent/prompts/system/reviewer.txt`（或 reviewer 节点代码）

**具体改动**：
1. 在 reviewer prompt 中增加：
   ```text
   【citation 检查范围】
   只需检查以下两类内容是否有来源：
   1. UP 方法论概念（如冰点期、分歧/修复、产业链扩散）。
   2. 引用 UP 历史观点或具体判断的句子。
   行情数据、实时盘面描述不需要引用。不要因此触发重试。
   ```
2. 如果 reviewer 代码会强制重试，修改逻辑：citation 问题只记录，不返回 style_writer 重试，除非涉及核心方法论无来源。

**验证步骤**：
1. 运行 10 次分析，统计 reviewer 因 citation 失败的次数，应接近 0。
2. 检查日志中 `reviewer: passed=True` 比例提升。

---

### Task 3.4：强制 stock_scanner 输出 upside/downside/ratio

**目标**：避免 reviewer 因为持仓/候选标的缺少赔率而失败。

**依赖**：无。

**修改文件**：`src/qing_investment/agent/prompts/system/stock_scanner.txt`

**具体改动**：
1. 在输出要求中增加：
   ```text
   【强制字段】
   对每一个具体标的（尤其是持仓股和机会候选），必须给出：
   - upside: 预期上涨空间（%或价格）
   - downside: 预期下跌空间（%或价格）
   - ratio: 赔率比（如 2:1）
   缺少这三个字段的输出将被视为不合格。
   ```
2. 在 JSON schema 中把 `upside`、`downside`、`ratio` 设为 required 字段。

**验证步骤**：
1. 触发买入信号候选分析。
2. 检查返回 JSON 中每个 opportunity 是否都包含 `upside`、`downside`、`ratio`。
3. 检查 reviewer 是否不再因"缺少赔率分析"失败。

---

## Phase 4：重构早盘节点，减少重复（P1）

### Task 4.1：修改 cron_opening.txt，聚焦剧本验证

**目标**：09:26 节点只做"昨日 tomorrow_scenarios vs 今日竞价"。

**依赖**：Task 1.4（daily_state 能稳定提供 yesterday scenarios）。

**修改文件**：`src/qing_investment/agent/prompts/system/cron_opening.txt`

**具体改动**：
1. 删除或弱化"早盘定性"、"主线确认"等内容。
2. 明确要求输出：
   ```text
   【输出要求】
   1. scenario_validation: 昨日 tomorrow_scenarios 中哪个情景匹配度最高，偏差是什么。
   2. core_assumption: 今天大概率是什么基调（一句话）。
   3. direction_priority: 最多 3 个方向的初判。
   4. position_action: 对持仓的应对。
   不要在此节点做完整分析，只给出核心假设和剧本验证。
   ```

**验证步骤**：
1. 触发 09:26 节点，检查输出是否以"剧本验证"为主。
2. 输出字数应控制在 250 字以内。

---

### Task 4.2：修改 cron_morning_confirm.txt，聚焦假设验证与结论固化

**目标**：10:00 节点明确基于 09:26 假设做验证，并给出今日基调。

**依赖**：Task 4.1。

**修改文件**：`src/qing_investment/agent/prompts/system/cron_morning_confirm.txt`

**具体改动**：
1. 在 prompt 开头注入 09:26 的核心假设（从 `daily_state.intraday_narrative` 读取）。
2. 输出要求改为：
   ```text
   【输出要求】
   1. assumption_validation: 09:26 的核心假设哪些成立、哪些被推翻。
   2. morning_character: 今日基调（强修复/弱修复/分歧/防御）。
   3. direction_priority: 排序后的方向，最多 3 个。
   4. opportunity_patterns: 今天可能触发的机会模式清单。
   ```
3. 删除与 09:26 重复的"早盘定性"大段描述。

**验证步骤**：
1. 触发 10:00 节点，检查输出是否引用了 09:26 假设。
2. 检查输出是否不再重复描述开盘竞价情况。

---

### Task 4.3：确保 intraday_narrative key 不互相覆盖

**目标**：09:26、09:45、10:00 三个节点写入不同的 narrative key。

**依赖**：Task 1.4。

**修改文件**：`src/qing_investment/agent/graph/nodes.py`

**具体改动**：
1. 在 `_persist_daily_state_from_market_context` 中，根据 trigger ID 选择 label：
   ```python
   trigger_id = state.get("trigger", {}).get("id", "unknown")
   label_map = {
       "open_auction": "09:26 剧本验证",
       "open_confirm": "09:45 假设验证",
       "morning_confirm": "10:00 结论固化",
       # ...
   }
   label = label_map.get(trigger_id, f"{now_time} 节点分析")
   ```
2. `add_intraday_narrative` 追加记录而不是覆盖。

**验证步骤**：
1. 顺序触发 09:26、09:45、10:00 节点。
2. 检查 `daily_state.json` 中 `intraday_narrative` 包含三条不同 label 的记录。

---

## Phase 5：9:00 亚洲盘前信息聚合（P1）

### Task 5.1：在 strategy_pack.yaml 增加 09:00 节点

**目标**：让调度器每天 09:00 触发亚洲盘前信息聚合。

**依赖**：无。

**修改文件**：`config/stock_monitor/strategy_pack.yaml`

**具体改动**：
1. 在 `agent_analysis_schedule` 最前面追加：
   ```yaml
   - id: pre_market
     time: '09:00'
     name: 亚洲盘前信息聚合
     focus: 美股隔夜收盘、日韩开盘后1小时走势、A50/期货/地缘风险，写入pre_market_brief供09:26使用。
   ```
2. 确保 `time` 是字符串 `'09:00'`。

**验证步骤**：
1. YAML 解析测试通过。
2. `AgentSchedule.from_config` 能识别 09:00 节点。

---

### Task 5.2：创建 cron_pre_market.txt prompt

**目标**：定义 09:00 节点的输出格式和内容要求。

**依赖**：Task 5.1。

**修改文件**：`src/qing_investment/agent/prompts/system/cron_pre_market.txt`

**具体改动**：
1. 写入 prompt：
   ```text
   【09:00 亚洲盘前信息聚合 — 节点专属指令】

   你现在需要聚合三类信息，为 09:26 集合竞价分析做准备：

   1. 美股隔夜：
      - 道指/纳指/标普500 涨跌幅
      - 费城半导体指数、英伟达、美光等核心科技股表现
      - 重要 AI/CSP 相关新闻
   2. 日韩开盘后 1 小时（约 08:00-09:00）：
      - KOSPI、日经 225 涨跌幅
      - 三星电子、SK 海力士、东京电子、软银等走势
      - 日韩半导体/AI 板块对隔夜美股的反馈
   3. 期货与地缘：
      - A50 期指
      - 原油、黄金、美元指数、10Y 美债
      - 地缘冲突、政策/监管消息

   【输出要求】
   格式：JSON
   {
     "us_overnight": {...},
     "asia_first_hour": {...},
     "futures_geopolitics": {...},
     "core_assumption": "亚洲盘对隔夜美股反馈偏X，A股开盘大概率...",
     "key_risks": ["风险1", "风险2"]
   }

   【强制要求：daily_state 输出】
   分析完成后，在回复末尾输出：
   ```daily_state
   {"pre_market_brief": {"us_overnight": {...}, "asia_first_hour": {...}, "futures_geopolitics": {...}, "core_assumption": "...", "key_risks": [...]}}
   ```
   ```

**验证步骤**：
1. 确认文件存在且能被 `_load_prompt` 读取。
2. 触发 09:00 节点，检查输出格式是否为 JSON + daily_state 代码块。

---

### Task 5.3：实现外部数据聚合 fetcher

**目标**：获取美股、日韩、期货等数据，供 09:00 节点使用。

**依赖**：Task 5.2。

**修改文件**：`src/qing_investment/agent/tools/external_market_fetcher.py`（新建）

**具体改动**：
1. 实现函数：
   ```python
   async def fetch_pre_market_brief() -> dict:
       result = {
           "us_overnight": {},
           "asia_first_hour": {},
           "futures_geopolitics": {},
           "errors": []
       }
       # 美股：调用现有 eastmoney/tencent 接口获取指数和个股
       # 日韩：通过 yahoo finance 或新浪接口获取 KOSPI/日经/三星/SK海力士
       # 期货：通过新浪期货接口获取 A50、原油、黄金
       # 每个数据源独立 try/except，超时 5 秒
       return result
   ```
2. 每个数据源独立超时控制，失败时不阻塞其他数据源。
3. 若全部失败，返回 `{"available": false}`。

**验证步骤**：
1. 单元测试 mock 各数据源，确认聚合结构正确。
2. 运行一次真实 fetch，检查是否有数据返回，超时数据源是否记录到 `errors`。

---

### Task 5.4：09:26 节点读取 pre_market_brief

**目标**：让 09:26 节点直接使用 09:00 聚合的信息，不再临时联网搜索。

**依赖**：Task 5.3、Task 4.1。

**修改文件**：`src/qing_investment/agent/graph/nodes.py`、`src/qing_investment/agent/prompts/system/cron_opening.txt`

**具体改动**：
1. 在 09:26 节点加载 `daily_state.pre_market_brief` 并注入 prompt。
2. 在 `cron_opening.txt` 顶部增加：
   ```text
   【09:00 亚洲盘前信息聚合结果】
   {pre_market_brief}
   请基于以上信息做剧本验证，不要再临时搜索外部信息。
   ```
3. 如果 `pre_market_brief` 为空或 `available: false`，则标注"外部数据不可用，仅基于知识库分析"。

**验证步骤**：
1. 先运行 09:00 节点，确认 `daily_state.pre_market_brief` 有数据。
2. 再运行 09:26 节点，检查日志中是否出现网络搜索调用（应明显减少）。
3. 检查 09:26 输出是否引用了日韩开盘后走势。

---

### Task 5.5：09:00 节点时限保护

**目标**：确保 09:00 节点在 09:25 前完成，否则降级。

**依赖**：Task 5.4。

**修改文件**：`src/qing_investment/monitor/scheduler/__init__.py`、调用 09:00 的 wrapper

**具体改动**：
1. 在调用 09:00 节点时设置整体超时 90 秒。
2. 若超时，直接写入一个空的 `pre_market_brief`：
   ```python
   save_daily_state(update_market_stage(load_daily_state(), phase="数据不可用", detail="09:00 节点超时", updated_by="pre_market:timeout"))
   ```
3. 记录 error log，不阻塞 09:26 节点。

**验证步骤**：
1. 模拟 09:00 节点超时，检查 09:26 是否正常触发。
2. 检查日志中是否有降级提示。

---

## Phase 6：统一机会生命周期管理（P1）

### Task 6.1：统一 active_opportunities schema

**目标**：所有节点写入统一格式的 opportunity。

**依赖**：Task 1.4。

**修改文件**：`src/qing_investment/agent/tools/daily_state.py`

**具体改动**：
1. 修改 `add_opportunity` 函数，统一字段并自动补全：
   ```python
   def add_opportunity(state, stock, code, pattern, trigger, upside, downside, ratio, status, entry_zone=None, stop_loss=None, source_node="unknown"):
       code = normalize_code(code)  # 统一加 .SZ/.SH
       state.setdefault("active_opportunities", [])
       now = datetime.now(_CN_TZ).isoformat()
       existing = next((o for o in state["active_opportunities"] if normalize_code(o.get("code")) == code), None)
       opp = {
           "stock": stock,
           "code": code,
           "pattern": pattern,
           "trigger": trigger,
           "status": status,
           "upside": upside,
           "downside": downside,
           "ratio": ratio,
           "entry_zone": entry_zone or [],
           "stop_loss": stop_loss,
           "first_seen_at": existing.get("first_seen_at", now) if existing else now,
           "last_checked_at": now,
           "source_node": source_node,
       }
       if existing:
           existing.update(opp)
       else:
           state["active_opportunities"].append(opp)
       return state
   ```
2. 增加 `normalize_code(code)` 辅助函数。

**验证步骤**：
1. 单元测试：多次添加同一 code，确认只保留一条记录且 `first_seen_at` 不变、`last_checked_at` 更新。
2. 确认 code 统一为 6 位数字 + `.SZ/.SH`。

---

### Task 6.2：在 closing_review 中刷新机会状态

**目标**：17:00 收盘复盘统一更新所有机会的触发/失效状态。

**依赖**：Task 1.3、Task 6.1。

**修改文件**：`src/qing_investment/agent/graph/nodes.py`、`src/qing_investment/agent/prompts/system/cron_closing.txt`

**具体改动**：
1. 在 17:00 节点运行前，读取持仓和 watchlist 的收盘价。
2. 对每个 `active_opportunity`，根据收盘价和 `entry_zone` 自动判断状态：
   - 收盘价在 entry_zone 内 → "未触发" 保持或改为"候选"
   - 收盘价跌破 stop_loss → "失效"
   - 已买入 → "已触发"
3. 在 `cron_closing.txt` 中要求 LLM 基于上述自动状态做最终复核，并输出明日观察列表。

**验证步骤**：
1. 构造几个测试机会，模拟收盘价变化。
2. 触发 17:00 节点，检查 `daily_state.active_opportunities` 状态是否正确更新。

---

### Task 6.3：清理失效机会

**目标**：避免 daily_state 无限增长。

**依赖**：Task 6.2。

**修改文件**：`src/qing_investment/agent/tools/daily_state.py`

**具体改动**：
1. 在 `save_daily_state` 中增加清理逻辑：
   ```python
   def _cleanup_opportunities(opportunities):
       kept = []
       for opp in opportunities:
           if opp.get("status") == "失效" and is_older_than(opp.get("last_checked_at"), days=3):
               continue
           kept.append(opp)
       return kept
   ```
2. 每天 17:00 保存时调用清理。

**验证步骤**：
1. 单元测试：构造 5 天前的失效机会，确认保存后被清理。

---

## Phase 7：校准 Agent 输出与 UP 复盘一致性（P1）

### Task 7.1：创建一致性评估脚本

**目标**：离线对比 Agent 预判与 UP 实际复盘。

**依赖**：Task 1.4、Task 6.2。

**修改文件**：`scripts/evaluate_agent_vs_up.py`（新建）

**具体改动**：
1. 实现：
   ```python
   def evaluate(date: str):
       agent_state = load_daily_state(date)
       up_claims = load_claims_by_date(date)  # 从 knowledge/claims/ 读取
       report = {
           "date": date,
           "direction_overlap": compare_directions(agent_state.get("direction_priority", []), up_claims),
           "assumption_accuracy": compare_assumptions(agent_state.get("tomorrow_assumption", ""), up_claims),
           "scenario_accuracy": compare_scenarios(agent_state.get("tomorrow_scenarios", {}), up_claims),
           "opportunity_hit_rate": compare_opportunities(agent_state.get("active_opportunities", []), up_claims),
       }
       return report
   ```
2. 对比逻辑用 LLM 或规则匹配（如方向关键词重合度）。

**验证步骤**：
1. 以 2026-07-08 为例运行脚本，生成报告。
2. 人工检查报告是否合理。

---

### Task 7.2：生成并保存周一致性报告

**目标**：每周自动生成报告。

**依赖**：Task 7.1。

**修改文件**：`scripts/evaluate_agent_vs_up.py`、cron 配置

**具体改动**：
1. 增加 `--week` 参数，批量跑最近 5 个交易日。
2. 输出 Markdown 报告到 `evals/agent-up-consistency/YYYY-MM-DD.md`。
3. 在 cron 中每周一早上 08:00 运行一次。

**验证步骤**：
1. 手动运行 `--week` 参数，确认报告生成。
2. 检查报告包含方向重合度、假设准确率、情景准确率、机会命中率。

---

## Phase 8：优化模型路由与降级（P2）

### Task 8.1：devils_advocate 使用默认 provider

**目标**：避免 KIMI_API_KEY 缺失导致跳过。

**依赖**：无。

**修改文件**：`src/qing_investment/agent/agents/devils_advocate.py` 或 `src/qing_investment/agent/graph/nodes.py`

**具体改动**：
1. 找到 `devils_advocate` 调用处，把硬编码 `kimi` 改为 `None` 或 `deepseek`。
2. 使用 `get_llm_client(target=None)` 走默认 provider。

**验证步骤**：
1. 删除或不设置 `KIMI_API_KEY`。
2. 触发分析，确认 `devils_advocate` 使用 deepseek 成功。

---

### Task 8.2：reviewer citation 问题不重试

**目标**：减少 token 浪费。

**依赖**：Task 3.3。

**修改文件**：`src/qing_investment/agent/graph/edges.py`（或 reviewer 路由逻辑）

**具体改动**：
1. 在 `review_router` 中，如果 reviewer issues 只包含 citation 相关且非核心方法论缺失，直接 `passed=True`。
2. 把 citation 修改建议作为下一轮 style_writer 的 prompt 注入，而不是重试。

**验证步骤**：
1. 模拟 citation 问题，检查是否不再触发 retry。
2. 统计单次分析的 LLM 调用次数，应明显下降。

---

## Phase 9：增加板块/情绪数据（P2）

### Task 9.1：扩展 market_snapshot 数据结构

**目标**：支持涨跌家数、涨跌停、连板高度等情绪指标。

**依赖**：无。

**修改文件**：`src/qing_investment/agent/models/schemas.py`、`src/qing_investment/monitor/scheduler/__init__.py`

**具体改动**：
1. 在 `market_snapshot` 中增加：
   ```python
   class MarketSnapshot(BaseModel):
       source: str
       quotes: list[Quote]
       sentiment: dict | None = None  # 新增
   ```
2. `sentiment` 字段包括：`up_count`, `down_count`, `limit_up_count`, `limit_down_count`, `consecutive_height`, `first_board_count`, `炸板率`。

**验证步骤**：
1. 单元测试序列化/反序列化。
2. 确认 `/analyze/trigger` 能接收带 sentiment 的请求。

---

### Task 9.2：从东方财富/同花顺获取情绪数据

**目标**：填充 sentiment 字段。

**依赖**：Task 9.1。

**修改文件**：`src/qing_investment/agent/tools/stock_data.py` 或新建 `src/qing_investment/agent/tools/market_sentiment.py`

**具体改动**：
1. 实现 `fetch_market_sentiment()`：
   - 调用东方财富 `http://push2ex.eastmoney.com/getTopicZDFRank` 或同花顺行情接口。
   - 返回涨跌家数、涨停数、连板高度等。
2. 在 monitor tick 中调用并写入 `market_snapshot.sentiment`。

**验证步骤**：
1. 运行一次真实 fetch，检查返回数据是否完整。
2. 在 09:26 节点触发后，检查 `market_snapshot` 是否包含 sentiment。

---

### Task 9.3：在 prompt 中使用情绪数据

**目标**：让 Agent 在分析时能看到情绪指标。

**依赖**：Task 9.2。

**修改文件**：`src/qing_investment/agent/prompts/system/market_summary.txt`（或 cron_opening.txt）

**具体改动**：
1. 在 prompt 顶部注入：
   ```text
   【市场情绪】
   涨跌家数：{up_count}/{down_count}
   涨停/跌停：{limit_up_count}/{limit_down_count}
   连板高度：{consecutive_height}
   首板数：{first_board_count}
   ```
2. 在分析要求中增加："结合情绪指标判断当前处于冰点/回暖/高潮/退潮哪个阶段"。

**验证步骤**：
1. 触发 09:26 节点，检查输出是否引用了涨跌家数或涨停数。
2. 检查 `market_stage.phase` 是否使用了情绪阶段词汇。

---

## 执行顺序总览

| 阶段 | 任务 | 预计工时 | 阻塞点 |
|------|------|---------|--------|
| Phase 1 | 1.1 - 1.4 | 1 天 | 无 |
| Phase 2 | 2.1 - 2.4 | 2 天 | Phase 1.4 |
| Phase 3 | 3.1 - 3.4 | 1 天 | 无 |
| Phase 4 | 4.1 - 4.3 | 1 天 | Phase 1.4 |
| Phase 5 | 5.1 - 5.5 | 2 天 | Phase 4.1 |
| Phase 6 | 6.1 - 6.3 | 1 天 | Phase 1.4 |
| Phase 7 | 7.1 - 7.2 | 1 天 | Phase 6.2 |
| Phase 8 | 8.1 - 8.2 | 0.5 天 | Phase 3.3 |
| Phase 9 | 9.1 - 9.3 | 1.5 天 | 无 |

**总计**：约 11 个工作日。

---

## 全局验收标准

| 检查项 | 通过标准 |
|--------|---------|
| 17:00 收盘复盘 | 连续 3 个交易日稳定触发，输出包含"观点演进回顾 + 预判 vs 实际" |
| 分片请求 | P1/持仓股单次 prompt 完整；其他 shard 单次 ≤ 64KB；09:30 前完成全部分片 |
| citation | 单次分析输出中 `[claim-xxx]` 引用 ≥ 3 处；reviewer 不因 citation 失败 |
| 早盘节点 | 09:26 输出以剧本验证为主；10:00 输出引用 09:26 假设 |
| 09:00 预聚合 | 09:25 前完成；09:26 不再临时联网搜索；包含日韩 1 小时数据 |
| 机会管理 | 同一 code 只出现一次；状态随价格自动刷新；失效 3 天后清理 |
| 一致性评估 | 每周生成报告；方向重合度可量化 |
| 情绪数据 | market_snapshot 包含涨跌家数、涨停数；Agent 输出引用情绪指标 |
