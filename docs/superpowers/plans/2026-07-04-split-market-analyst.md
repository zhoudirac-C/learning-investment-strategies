# Split market_analyst into market_summary + stock_scanner

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the oversized `market_analyst` node into a `market_summary` node (market/sector analysis only) and a `stock_scanner` node (portfolio/watchlist scan), keeping the existing `market_context` output schema intact and reducing per-node prompt length below the local CLI argv limit.

**Architecture:** Add two new nodes to the LangGraph; `market_summary` consumes market-level context and writes a slim `market_summary_context`, then `stock_scanner` consumes that plus per-stock context to produce the full `market_context`. The existing `market_analyst` function is kept temporarily for A/B comparison.

**Tech Stack:** Python 3.12, LangGraph, existing Qing-Agent codebase.

## Global Constraints

- Prompt length for any single LLM call must stay < 64KB to leave headroom under Linux `ARG_MAX`.
- Output schema of `market_context` must remain backward-compatible.
- All new functions must log input sizes, prompt length, and duration.
- Tests must use `tmp/agent_context_sample.json` as a fixture.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/qing_investment/agent/graph/state.py` | Add `market_summary_context` typed field. |
| `src/qing_investment/agent/prompts/system/market_summary.txt` | System prompt for market/sector analysis. |
| `src/qing_investment/agent/prompts/system/stock_scanner.txt` | System prompt for portfolio/watchlist scan. |
| `src/qing_investment/agent/graph/nodes.py` | Add `market_summary()` and `stock_scanner()`; update builder import; keep old `market_analyst()` for comparison. |
| `src/qing_investment/agent/graph/builder.py` | Replace `market_analyst` with `market_summary → stock_scanner` in graph topology. |
| `tests/test_market_analyst_split.py` | Regression tests for prompt length and output schema. |

---

## Task 1: Extend AgentState with market_summary_context

**Files:**
- Modify: `src/qing_investment/agent/graph/state.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `AgentState["market_summary_context"]: dict | None`

- [ ] **Step 1: Add field to AgentState**

Add after `market_context: dict`:

```python
# 拆分 market_analyst 后的中间状态：精简市场背景，供 stock_scanner 使用
market_summary_context: dict | None
```

- [ ] **Step 2: Verify import/typing still valid**

Run:
```bash
cd /home/ubuntu/learning-investment-strategies && .venv/bin/python -c "from src.qing_investment.agent.graph.state import AgentState; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/qing_investment/agent/graph/state.py
git commit -m "feat(agent): add market_summary_context to AgentState"
```

---

## Task 2: Create market_summary system prompt

**Files:**
- Create: `src/qing_investment/agent/prompts/system/market_summary.txt`

**Interfaces:**
- Consumes: loaded by `_load_prompt("market_summary")`.
- Produces: a text file.

- [ ] **Step 1: Extract market-level instructions from market_analyst.txt**

Copy the relevant sections from `market_analyst.txt` (lines 1-115 roughly: real-time data rules, framework/claims usage, reasoning patterns step 1-3, methodology citations, timeliness, prohibitions, analysis_framework placeholder, output JSON schema excluding opportunity_scan/position_plans).

- [ ] **Step 2: Write market_summary.txt**

```text
【分析时必须获取的实时数据】
- 大盘指数：上证、深证、创业板、科创50、全A指数(中证全指)的开盘/最高/最低/收盘/涨跌
  - ⚠️ 全A指数=等权覆盖全市场，与上证（权重股主导）常有分化
  - UP核心观察：全A是否走中阳线？全A与科技/中小盘是否共振？这是判断"真修复"vs"假修复"的关键
- 成交量：两市总成交额、较前日变化、量能趋势
- 板块数据：领涨/领跌板块、涨停家数分布、板块轮动结构
- 情绪指标：涨跌家数、涨停/跌停数、连板高度、炸板率

【输入数据说明】
- claims: 博主观点（⏱ ≤7天→最新/8-30天→近期/31-90天→历史，按时效分级使用）
- wiki_snippets: UP原始文档片段（⚠️ 仅作方法论参考，不得作为事实依据）
- framework_rules: 分析方法论框架（✅ 指导如何思考，可引用概念来源）
- reasoning_patterns: 推理模式模板（✅ 指导分析步骤顺序）
- external_sector_boards: 外部行情源的完整板块数据（✅ 主要依据）
- market_snapshot: 实时行情快照（✅ 主要依据）
- sector_context: 动态板块+新闻（✅ 辅助依据）
- direction_signals: 方向优先级信号（UP对各方向的看好程度）

【数据使用优先级】
1. 最高优先：external_sector_boards、market_snapshot（实时数据）
2. 中优先：sector_context.news（最新动态）
3. 中低优先：claims中的【最新】标签
4. 低优先：framework_rules（方法论指导）
5. 禁止作为依据：历史claims、wiki_snippets的历史描述

【推理模式激活规则】
Step 1: 【市场阶段判断】确认市场处于什么阶段？核心矛盾？主线与过渡？
Step 2: 【方向筛选】候选方向是否满足政策级别/海外锚点/产业景气/资金认可？
Step 3: 【上游周期品分析】如涉及涨价链，确认真实性、供需驱动、历史位置、受益标的映射。

【方法论引用规则】
- 当使用UP特有的分析概念时，必须在citations中注明概念来源。
- 禁止引用claims作为方法论来源。

【禁止行为】
- 禁止以"UP之前说过..."作为当前判断依据
- 禁止引用claim ID支持当前观点
- 禁止在缺乏实时数据时编造分析
- 禁止给出无条件买卖指令

{analysis_framework}

输出格式：严格JSON
{
  "market_summary": "当日定调的一句话总结（基于实时数据）",
  "market_phase": "回暖期",
  "phase_reasoning": "基于实时数据的判断...",
  "main_themes": ["光互连", "半导体"],
  "sector_map": {
    "主攻层": [{"name": "光互连", "status": "主升", "key_stocks": ["亨通光电"], "logic": "..."}],
    "上游层": [],
    "防御层": [],
    "其他": []
  },
  "themes_in_focus": [
    {"theme": "...", "catalyst": "...", "risk": "...", "key_stocks": ["..."]}
  ],
  "index_discipline": {
    "support": "3950",
    "resistance": "4000",
    "action_below": "...",
    "action_above": "...",
    "middle_zone": "..."
  },
  "volume_note": "...",
  "emotion_signals": {"涨停": 50, "跌停": 8, "连板高度": 5, "炸板率": "35%"},
  "risk_notes": "...",
  "citations": ["framework/market-cycle-framework.md"]
}

【daily_state 输出格式】
在最终回复末尾，**必须**用 ```daily_state 代码块输出今日盘中观点的结构化摘要。
根据当前分析时间点，输出对应字段：
- 09:26 / 09:45 / 10:00 / 10:30 / 11:20 / 13:10 / 14:00 / 14:55 / 15:20 等
```

- [ ] **Step 3: Verify file loads**

Run:
```bash
cd /home/ubuntu/learning-investment-strategies && .venv/bin/python - << 'PY'
from pathlib import Path
p = Path("src/qing_investment/agent/prompts/system/market_summary.txt")
print(p.exists(), len(p.read_text(encoding="utf-8")))
PY
```

Expected: `True 2000+`

- [ ] **Step 4: Commit**

```bash
git add src/qing_investment/agent/prompts/system/market_summary.txt
git commit -m "feat(agent): add market_summary system prompt"
```

---

## Task 3: Create stock_scanner system prompt

**Files:**
- Create: `src/qing_investment/agent/prompts/system/stock_scanner.txt`

**Interfaces:**
- Consumes: loaded by `_load_prompt("stock_scanner")`.
- Produces: a text file.

- [ ] **Step 1: Extract stock-scan instructions from market_analyst.txt**

Copy opportunity-scan rules, position_plans rules, watchlist_summary usage rules, reference_stocks rules, and daily_state opportunity fields.

- [ ] **Step 2: Write stock_scanner.txt**

```text
【任务】
在市场背景已经确定的前提下，扫描持仓和观察池，生成：
1. opportunity_scan：今日值得关注的 3-5 只标的
2. position_plans：每只持仓的具体操作计划

【市场背景】
{market_summary_context}

【输入数据说明】
- positions: 当前持仓（含成本、现价、股数、止损/减仓条件）
- watchlist_summary: 观察池标的（按P1/P2/P3优先级，含介入区间、生命周期、UP情绪）
- reference_stocks: 创业板/科创板锚点（仅作情绪参考，不可操作）
- stock_contexts: 每只目标标的的UP claims摘要
- direction_signals: 方向优先级信号
- market_snapshot: 精简行情快照（指数+持仓+候选）

【watchlist_summary 使用规则】
- 按优先级排序：P1=最核心 → P2=重点 → P3=一般观察
- 机会扫描必须检查：①价格接近entry_zone ②板块异动 ③技术面确认 ④claims支持
- 已过介入窗口（>+15%）→标注「等下次回踩」
- 价格进入介入区间且 watch_reason 有效→标注「🟢 可能触发」
- 接近/跌破 risk_zone→标注「🔴 止损关注」

【reference_stocks 使用规则】
- 创业板(300)/科创板(688)标的仅作方向/情绪参考，不可操作
- 可标注「XX板块有参考标的大涨→板块方向验证」

【持仓计划规则】
- 对每只持仓给出：trigger（持有/加仓条件）、invalidation（减仓/止损条件）、position_advice
- 结合成本、现价、浮盈、所属板块强度

【赔率计算规则】
- 错了亏多少？对了赚多少？赔率是否 >= 2:1？
- 当前是否处于"分歧回踩"位置？加速段不参与

【禁止行为】
- 禁止无条件买卖指令
- 禁止默认输出"继续观察"
- 禁止编造实时数据

输出格式：严格JSON
{
  "opportunity_scan": [
    {
      "stock": "万泽股份",
      "code": "000534",
      "pattern": "技术支撑确认",
      "trigger": "回踩30.5-31.0企稳",
      "odds": "3:1",
      "upside_pct": 15,
      "downside_pct": 5,
      "confidence": "中",
      "reason": "..."
    }
  ],
  "position_plans": [
    {
      "code": "600246.SH",
      "name": "万通发展",
      "shares": 300,
      "cost": 16.203,
      "latest": 18.87,
      "trigger": "...",
      "invalidation": "...",
      "position_advice": "..."
    }
  ]
}

【daily_state 输出格式】
在最终回复末尾，**必须**用 ```daily_state 代码块输出机会扫描摘要，例如：
{"active_opportunities":[{"stock":"...","code":"...","pattern":"...","trigger":"...","odds":"...","status":"未触发"}]}
```

- [ ] **Step 3: Verify file loads**

Run:
```bash
cd /home/ubuntu/learning-investment-strategies && .venv/bin/python - << 'PY'
from pathlib import Path
p = Path("src/qing_investment/agent/prompts/system/stock_scanner.txt")
print(p.exists(), len(p.read_text(encoding="utf-8")))
PY
```

Expected: `True 1500+`

- [ ] **Step 4: Commit**

```bash
git add src/qing_investment/agent/prompts/system/stock_scanner.txt
git commit -m "feat(agent): add stock_scanner system prompt"
```

---

## Task 4: Implement market_summary node

**Files:**
- Modify: `src/qing_investment/agent/graph/nodes.py`

**Interfaces:**
- Consumes: `state["query"]`, `state["parsed_intent"]`, `state["market_snapshot"]`, `state["sector_strengths"]`, `state["external_sector_boards"]`, `state["sector_context"]`, `state["claims"]`, `state["wiki_snippets"]`, `state["memories"]`, `state["reasoning_patterns"]` (via `_load_reasoning_patterns`), `state["direction_signals"]`.
- Produces: `state["market_summary_context"]: dict` and `state["reasoning_steps"]: list`.

- [ ] **Step 1: Add helper to build slim market snapshot**

Insert near existing `_build_quote_lookup`:

```python
def _slim_market_snapshot_for_summary(market_snapshot: dict) -> dict:
    """为 market_summary 保留指数+关键市场数据，去掉个股明细。"""
    if not market_snapshot:
        return {}
    quotes = market_snapshot.get("quotes", []) or []
    market_indexes = {"000001", "399001", "399006", "000688", "000985", "000016", "000300", "000905", "000852", "399303"}
    slim_quotes = [
        q for q in quotes
        if (q.get("secid") and q.get("secid").split(".")[0] in market_indexes)
        or (q.get("code") and q.get("code").split(".")[0] in market_indexes)
        or "指数" in (q.get("label") or "")
    ]
    return {
        **market_snapshot,
        "quotes": slim_quotes,
        "_slim_from": len(quotes),
    }
```

- [ ] **Step 2: Implement market_summary function**

Add after `_load_reasoning_patterns` or near `market_analyst`:

```python
def market_summary(state: AgentState) -> AgentState:
    """市场/板块分析节点：只输出精简市场背景，不处理个股。"""
    logger = logging.getLogger(__name__)
    _t0 = time.time()
    prompt_template = _load_prompt("market_summary")
    analysis_type = (state.get("parsed_intent") or {}).get("analysis_type", "stock")

    market_snapshot = _slim_market_snapshot_for_summary(state.get("market_snapshot") or {})
    claims = state.get("claims", []) or []
    methodology_claims = _filter_methodology_only(claims)
    wiki_snippets = [
        s for s in (state.get("wiki_snippets", []) or [])
        if s.get("source", "").startswith("framework/") or "投资方法论" in s.get("source", "")
    ]
    framework_context = _load_framework_files(analysis_type)
    reasoning_patterns = _load_reasoning_patterns(state)
    esb = state.get("external_sector_boards", {})

    logger.info(
        "market_summary_input: quotes=%d claims=%d wiki=%d framework=%d patterns=%d esb_available=%s",
        len(market_snapshot.get("quotes", [])),
        len(methodology_claims),
        len(wiki_snippets),
        len(framework_context),
        len(reasoning_patterns),
        esb.get("available"),
    )

    analysis_framework = _load_analysis_framework()
    prompt_template_filled = prompt_template.replace("{analysis_framework}", analysis_framework)

    context = {
        "market_snapshot": market_snapshot,
        "sector_strengths": state.get("sector_strengths", []),
        "external_sector_boards": esb,
        "sector_context": state.get("sector_context", []),
        "claims": methodology_claims,
        "wiki_snippets": wiki_snippets,
        "framework_rules": framework_context,
        "reasoning_patterns": reasoning_patterns,
        "direction_signals": state.get("direction_signals", {}),
        "memories": state.get("memories", []),
    }

    prompt = f"""{prompt_template_filled}

{state.get("_data_missing_note", "")}

检索到的知识：
{json.dumps(context, ensure_ascii=False, indent=2, default=str)}

请输出JSON：
"""
    content = _safe_llm_invoke(prompt)
    _t1 = time.time()
    logger.info(
        "market_summary_llm: duration=%.1fs prompt_len=%d content_len=%d",
        _t1 - _t0, len(prompt), len(content) if content else 0
    )

    import re as _re
    cleaned_content = _re.sub(r"```daily_state\s*[\s\S]*?```", "", content or "").strip() if content else ""
    try:
        result = json.loads(cleaned_content) if cleaned_content else {}
    except json.JSONDecodeError:
        result = {}

    if not result:
        result = {
            "market_summary": "",
            "market_phase": "未配置",
            "phase_reasoning": "LLM未返回结果或API未配置",
            "main_themes": [],
            "sector_map": {},
            "themes_in_focus": [],
            "index_discipline": {},
            "volume_note": "",
            "emotion_signals": {},
            "risk_notes": "",
            "citations": [],
        }

    # daily_state 提取留到 stock_scanner 合并写入
    return {
        "market_summary_context": result,
        "reasoning_steps": [f"市场总结: {result.get('market_phase', 'N/A')}"],
    }
```

- [ ] **Step 3: Run smoke test**

Create a temporary smoke script and run it:

```bash
cd /home/ubuntu/learning-investment-strategies && .venv/bin/python - << 'PY'
import sys
sys.path.insert(0, "src")
import json
from pathlib import Path
from qing_investment.agent.graph.nodes import market_summary
from qing_investment.agent.graph.state import AgentState

data = json.loads(Path("tmp/agent_context_sample.json").read_text(encoding="utf-8"))
state: AgentState = {
    "query": data.get("trigger", {}).get("title", "") + "：" + data.get("trigger", {}).get("reason", ""),
    "parsed_intent": {"analysis_type": "market"},
    "market_snapshot": data.get("quote_snapshot", {}),
    "sector_strengths": data.get("sector_strengths", []),
    "external_sector_boards": data.get("external_sector_boards", {}),
    "sector_context": data.get("sector_context", []),
    "claims": data.get("claims", []),
    "wiki_snippets": data.get("wiki_snippets", []),
    "memories": data.get("memories", []),
    "reasoning_steps": [],
}
result = market_summary(state)
print("market_summary_context keys:", list(result.get("market_summary_context", {}).keys()))
PY
```

Expected: keys include `market_summary`, `market_phase`, `main_themes`, `sector_map`, etc.

- [ ] **Step 4: Commit**

```bash
git add src/qing_investment/agent/graph/nodes.py
git commit -m "feat(agent): implement market_summary node"
```

---

## Task 5: Implement stock_scanner node

**Files:**
- Modify: `src/qing_investment/agent/graph/nodes.py`

**Interfaces:**
- Consumes: `state["market_summary_context"]`, `state["market_snapshot"]`, `state["stock_contexts"]`, `state["watchlist"]`, `state["positions"]`, `state["direction_signals"]`, `state["parsed_intent"]`.
- Produces: `state["market_context"]: dict` and `state["reasoning_steps"]: list`.

- [ ] **Step 1: Add helper to build watchlist summary for scanner**

Reuse existing watchlist_summary logic from `market_analyst` (lines 1414-1500) by extracting it into `_build_watchlist_summary(watchlist_raw, positions, market_snapshot)`.

- [ ] **Step 2: Implement stock_scanner function**

```python
def stock_scanner(state: AgentState) -> AgentState:
    """个股扫描节点：基于市场背景扫描持仓和观察池。"""
    logger = logging.getLogger(__name__)
    _t0 = time.time()
    prompt_template = _load_prompt("stock_scanner")

    market_summary_ctx = state.get("market_summary_context") or {}
    market_snapshot = dict(state.get("market_snapshot") or {})

    # 精简行情快照：保留指数 + 持仓 + 高优先级 watchlist
    all_quotes = market_snapshot.get("quotes", []) or []
    codes_to_keep: set[str] = set()
    for p in state.get("positions", []) or []:
        code = str(p.get("code", "")).replace(".SH", "").replace(".SZ", "")
        if code:
            codes_to_keep.add(code)
    for w in state.get("watchlist", []) or []:
        code = str(w.get("code", "")).replace(".SH", "").replace(".SZ", "")
        if code:
            codes_to_keep.add(code)
    filtered = [q for q in all_quotes if _pure_stock_code(q.get("code")) in codes_to_keep]
    market_snapshot["quotes"] = filtered
    market_snapshot["_filtered_from"] = len(all_quotes)

    watchlist_summary, reference_stocks = _build_watchlist_summary(
        state.get("watchlist", []), state.get("positions", []), market_snapshot
    )

    logger.info(
        "stock_scanner_input: market_summary_len=%d stock_contexts=%d watchlist_summary=%d reference=%d positions=%d",
        len(json.dumps(market_summary_ctx, ensure_ascii=False, default=str)),
        len(state.get("stock_contexts", [])),
        len(watchlist_summary),
        len(reference_stocks),
        len(state.get("positions", [])),
    )

    context = {
        "market_summary_context": market_summary_ctx,
        "market_snapshot": market_snapshot,
        "positions": state.get("positions", []),
        "watchlist_summary": watchlist_summary,
        "reference_stocks": reference_stocks,
        "stock_contexts": state.get("stock_contexts", []),
        "direction_signals": state.get("direction_signals", {}),
    }

    prompt = f"""{prompt_template}

上下文：
{json.dumps(context, ensure_ascii=False, indent=2, default=str)}

请输出JSON：
"""
    content = _safe_llm_invoke(prompt)
    _t1 = time.time()
    logger.info(
        "stock_scanner_llm: duration=%.1fs prompt_len=%d content_len=%d",
        _t1 - _t0, len(prompt), len(content) if content else 0
    )

    import re as _re
    cleaned_content = _re.sub(r"```daily_state\s*[\s\S]*?```", "", content or "").strip() if content else ""
    try:
        scan_result = json.loads(cleaned_content) if cleaned_content else {}
    except json.JSONDecodeError:
        scan_result = {}

    # 合并 market_summary 的输出
    full_market_context = dict(market_summary_ctx)
    full_market_context.setdefault("opportunity_scan", scan_result.get("opportunity_scan", []))
    full_market_context.setdefault("position_plans", scan_result.get("position_plans", []))

    if not scan_result:
        full_market_context["opportunity_scan"] = []
        full_market_context["position_plans"] = []

    return {
        "market_context": full_market_context,
        "reasoning_steps": [
            f"个股扫描: opportunities={len(full_market_context.get('opportunity_scan', []))} positions={len(full_market_context.get('position_plans', []))}"
        ],
    }
```

- [ ] **Step 3: Run smoke test**

```bash
cd /home/ubuntu/learning-investment-strategies && .venv/bin/python - << 'PY'
import sys
sys.path.insert(0, "src")
import json
from pathlib import Path
from qing_investment.agent.graph.nodes import stock_scanner
from qing_investment.agent.graph.state import AgentState

data = json.loads(Path("tmp/agent_context_sample.json").read_text(encoding="utf-8"))
state: AgentState = {
    "market_summary_context": {"market_phase": "回暖期", "main_themes": ["半导体"]},
    "market_snapshot": data.get("quote_snapshot", {}),
    "stock_contexts": data.get("stock_contexts", []),
    "watchlist": data.get("watchlist", []),
    "positions": data.get("positions", []),
    "direction_signals": data.get("direction_signals", {}),
    "parsed_intent": {"analysis_type": "market"},
    "reasoning_steps": [],
}
result = stock_scanner(state)
print("market_context keys:", list(result.get("market_context", {}).keys()))
PY
```

Expected: keys include `market_phase`, `main_themes`, `opportunity_scan`, `position_plans`.

- [ ] **Step 4: Commit**

```bash
git add src/qing_investment/agent/graph/nodes.py
git commit -m "feat(agent): implement stock_scanner node"
```

---

## Task 6: Update graph topology

**Files:**
- Modify: `src/qing_investment/agent/graph/builder.py`

**Interfaces:**
- Consumes: `market_summary`, `stock_scanner` from nodes.
- Produces: updated graph with `market_summary → stock_scanner` replacing `market_analyst`.

- [ ] **Step 1: Update imports**

```python
from .nodes import (
    citation_validator,
    devils_advocate,
    market_summary,      # replace market_analyst
    parse_query,
    retrieve_knowledge,
    reviewer,
    stock_analyst,
    stock_scanner,       # new
    style_writer,
    synthesize,
)
```

- [ ] **Step 2: Update graph wiring**

```python
builder.add_node("market_summary", market_summary)
builder.add_node("stock_scanner", stock_scanner)
# ... other nodes ...

builder.set_entry_point("parse_query")
builder.add_edge("parse_query", "retrieve_knowledge")
builder.add_edge("retrieve_knowledge", "market_summary")
builder.add_edge("retrieve_knowledge", "stock_analyst")
builder.add_edge("market_summary", "stock_scanner")
builder.add_edge("stock_scanner", "devils_advocate")
builder.add_edge("stock_analyst", "devils_advocate")
# rest unchanged
```

- [ ] **Step 3: Update topology log message**

Change the log in `build_graph` to:
```python
logger.info("[build_graph] topology: parse_query → retrieve_knowledge → market_summary → stock_scanner + stock_analyst → devils_advocate → ...")
```

- [ ] **Step 4: Run smoke test**

```bash
cd /home/ubuntu/learning-investment-strategies && .venv/bin/python - << 'PY'
import sys
sys.path.insert(0, "src")
from qing_investment.agent.graph.builder import build_graph
g = build_graph()
print("nodes:", list(g.nodes.keys()))
PY
```

Expected: nodes list contains `market_summary`, `stock_scanner`, no `market_analyst`.

- [ ] **Step 5: Commit**

```bash
git add src/qing_investment/agent/graph/builder.py
git commit -m "feat(agent): wire market_summary and stock_scanner into graph"
```

---

## Task 7: Add regression test

**Files:**
- Create: `tests/test_market_analyst_split.py`

**Interfaces:**
- Consumes: `tmp/agent_context_sample.json`, `build_graph()`.
- Produces: pytest test cases.

- [ ] **Step 1: Write test file**

```python
import json
from pathlib import Path

import pytest

ROOT = Path("/home/ubuntu/learning-investment-strategies")


def _load_sample():
    with open(ROOT / "tmp" / "agent_context_sample.json", encoding="utf-8") as f:
        return json.load(f)


def _build_state(data: dict) -> dict:
    return {
        "query": f"{data.get('trigger', {}).get('title', '')}：{data.get('trigger', {}).get('reason', '')}",
        "session_id": f"hermes-{data.get('timestamp', 'now')}",
        "parsed_intent": {"analysis_type": data.get("analysis_type", "market")},
        "trigger": data.get("trigger", {}),
        "alerts": data.get("alerts", []),
        "buy_signal_candidates": data.get("buy_signal_candidates", []),
        "market_snapshot": data.get("quote_snapshot", {}),
        "positions": data.get("positions", []),
        "watchlist": data.get("watchlist", []),
        "sector_strengths": data.get("sector_strengths", []),
        "external_sector_boards": data.get("external_sector_boards", {}),
        "claims": data.get("claims", []),
        "wiki_snippets": data.get("wiki_snippets", []),
        "sector_context": data.get("sector_context", []),
        "memories": data.get("memories", []),
        "stock_contexts": data.get("stock_contexts", []),
        "direction_signals": data.get("direction_signals", {}),
        "reasoning_steps": [],
    }


def test_graph_has_new_nodes():
    sys.path.insert(0, str(ROOT / "src"))
    from qing_investment.agent.graph.builder import build_graph
    g = build_graph()
    assert "market_summary" in g.nodes
    assert "stock_scanner" in g.nodes
    assert "market_analyst" not in g.nodes


def test_market_summary_prompt_length():
    sys.path.insert(0, str(ROOT / "src"))
    from qing_investment.agent.graph.nodes import market_summary
    data = _load_sample()
    state = _build_state(data)
    # smoke: ensure function runs without LLM call by patching if needed
    # For now just assert the prompt construction does not explode
    import qing_investment.agent.graph.nodes as nodes
    original_invoke = nodes._safe_llm_invoke
    captured = {}
    def fake_invoke(prompt, min_length=0):
        captured["prompt_len"] = len(prompt)
        return json.dumps({"market_phase": "回暖期", "main_themes": []})
    nodes._safe_llm_invoke = fake_invoke
    try:
        result = market_summary(state)
        assert "market_summary_context" in result
        assert captured["prompt_len"] < 64000, f"prompt too long: {captured['prompt_len']}"
    finally:
        nodes._safe_llm_invoke = original_invoke


def test_stock_scanner_prompt_length():
    sys.path.insert(0, str(ROOT / "src"))
    from qing_investment.agent.graph.nodes import stock_scanner
    data = _load_sample()
    state = _build_state(data)
    state["market_summary_context"] = {
        "market_phase": "回暖期",
        "main_themes": ["半导体"],
        "sector_map": {},
        "risk_notes": "",
    }
    import qing_investment.agent.graph.nodes as nodes
    original_invoke = nodes._safe_llm_invoke
    captured = {}
    def fake_invoke(prompt, min_length=0):
        captured["prompt_len"] = len(prompt)
        return json.dumps({"opportunity_scan": [], "position_plans": []})
    nodes._safe_llm_invoke = fake_invoke
    try:
        result = stock_scanner(state)
        assert "market_context" in result
        assert captured["prompt_len"] < 64000, f"prompt too long: {captured['prompt_len']}"
    finally:
        nodes._safe_llm_invoke = original_invoke
```

- [ ] **Step 2: Run tests**

```bash
cd /home/ubuntu/learning-investment-strategies && .venv/bin/python -m pytest tests/test_market_analyst_split.py -v
```

Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_market_analyst_split.py
git commit -m "test(agent): add regression tests for market_analyst split"
```

---

## Task 8: Restart Qing-Agent and verify

**Files:**
- None.

- [ ] **Step 1: Restart service**

```bash
pkill -f 'uvicorn.*qing_investment'
sleep 2
bash /home/ubuntu/learning-investment-strategies/scripts/start_qing_agent.sh
```

- [ ] **Step 2: Health check**

```bash
sleep 15 && curl -s http://127.0.0.1:8000/health
```

Expected: `{"status":"ok","version":"0.1.0"}`

- [ ] **Step 3: Trigger a test analysis**

```bash
curl -s -X POST http://127.0.0.1:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d @/home/ubuntu/learning-investment-strategies/tmp/agent_context_sample.json | head -c 500
```

Expected: HTTP 200 and UP-style output beginning.

- [ ] **Step 4: Inspect logs for new nodes**

```bash
tail -100 /home/ubuntu/learning-investment-strategies/logs/qing-agent.log | grep -E "market_summary|stock_scanner|prompt_len"
```

Expected: lines showing `market_summary_input`, `market_summary_llm`, `stock_scanner_input`, `stock_scanner_llm`.

---

## Self-Review Checklist

- [ ] Spec coverage: every design section has a corresponding task.
- [ ] Placeholder scan: no "TBD", "TODO", "implement later" in plan.
- [ ] Type consistency: `market_summary_context` used consistently across state, nodes, builder.
- [ ] Backward compatibility: `market_context` output schema unchanged.
- [ ] Local CLI safety: both new nodes log prompt length; tests assert < 64KB.
