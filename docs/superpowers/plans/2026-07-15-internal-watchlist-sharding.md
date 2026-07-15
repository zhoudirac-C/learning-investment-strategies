# Internal Watchlist Sharding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move watchlist sharding from the external cron script into the qing-agent LangGraph so that `retrieve_knowledge` and `market_summary` run once per trigger, and `stock_scanner` runs in parallel per sector shard.

**Architecture:** Add a `shard_router` conditional node after `market_summary` that emits `Send("stock_scanner_shard", ...)` for each shard. Each `stock_scanner_shard` node returns its result into an `Annotated[list[dict], operator.add]` field. A new `merge_scanner_results` node fans the list back into a single `market_context`, persists `daily_state` once, and hands off to the existing downstream nodes. The external cron script stops calling `/analyze/trigger` multiple times.

**Tech Stack:** Python 3.11, LangGraph, Pydantic, existing `watchlist_sharder.py`.

## Global Constraints

- Keep existing `/chat` endpoint behavior unchanged.
- Do not break the existing single-shot `stock_analyst` path for individual-stock queries.
- Preserve backward compatibility for `TriggerRequest`: new fields must have safe defaults.
- `WATCHLIST_SHARD_SIZE` env var must still be honored, but read inside the agent rather than in the cron script.
- All existing tests in `tests/test_qing_agent_monitor_workflow.py` must pass after updates.
- Use `operator.add` as the reducer for list fields produced by parallel nodes.
- Do not remove `watchlist_sharder.py`; reuse it inside `shard_router`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/qing_investment/agent/graph/state.py` | Add `stock_scanner_results` (parallel accumulator) and `shard_size`/`core_only` control fields. |
| `src/qing_investment/agent/models/schemas.py` | Add `shard_size` and `core_only` to `TriggerRequest` with defaults. |
| `src/qing_investment/agent/main.py` | Pass `shard_size`/`core_only` from `TriggerRequest` into the initial `AgentState`. |
| `src/qing_investment/agent/graph/nodes.py` | Add `shard_router`, `stock_scanner_shard`, `merge_scanner_results`; remove the in-function bisect fallback. |
| `src/qing_investment/agent/graph/builder.py` | Wire `market_summary → shard_router → [stock_scanner_shard] → merge_scanner_results → devils_advocate`. |
| `scripts/hermes_stock_monitor_agent.py` | Remove external sharding, `ThreadPoolExecutor`, and aggregation; call `/analyze/trigger` once. |
| `tests/test_qing_agent_monitor_workflow.py` | Update mock expectations and graph-path assertions for the new topology. |

---

## Task 1: Extend AgentState for parallel scanner results

**Files:**
- Modify: `src/qing_investment/agent/graph/state.py`
- Test: `tests/test_qing_agent_monitor_workflow.py` (indirectly)

**Interfaces:**
- Consumes: `operator` and `Annotated` from `typing`.
- Produces: `stock_scanner_results: Annotated[list[dict], operator.add]`, `shard_size: int`, `core_only: bool` fields on `AgentState`.

- [ ] **Step 1: Add imports and new fields**

At the top of `src/qing_investment/agent/graph/state.py`, add `import operator` after the `from __future__` line.

Inside `AgentState`, add these fields (place them near the other analysis-layer fields):

```python
import operator

# ... existing imports and helper functions ...

class AgentState(TypedDict, total=False):
    # ... all existing fields ...

    # Phase 2 新增：watchlist 分片输入（保留，单 shard 场景仍可用）
    watchlist_shard: dict | None

    # 【新增】内部分片并行控制
    shard_size: int
    core_only: bool

    # 【新增】并行 stock_scanner 分片结果累加器
    stock_scanner_results: Annotated[list[dict], operator.add]

    # 分析层
    market_context: dict
    # ... rest unchanged ...
```

- [ ] **Step 2: Verify the module imports**

Run:

```bash
cd /home/ubuntu/learning-investment-strategies
.venv/bin/python -c "from qing_investment.agent.graph.state import AgentState; print('state import OK')"
```

Expected: `state import OK` with no `ImportError`.

- [ ] **Step 3: Commit**

```bash
git add src/qing_investment/agent/graph/state.py
git commit -m "feat(agent): add stock_scanner_results accumulator and shard controls to AgentState"
```

---

## Task 2: Add shard controls to TriggerRequest

**Files:**
- Modify: `src/qing_investment/agent/models/schemas.py`
- Test: `tests/test_qing_agent_monitor_workflow.py` (indirectly)

**Interfaces:**
- Consumes: existing `TriggerRequest`.
- Produces: `TriggerRequest.shard_size: int = 8`, `TriggerRequest.core_only: bool = False`.

- [ ] **Step 1: Add fields**

In `src/qing_investment/agent/models/schemas.py`, add two new fields to `TriggerRequest` after `watchlist_shard`:

```python
class TriggerRequest(BaseModel):
    # ... existing fields ...
    watchlist_shard: dict | None = Field(default=None, description="当前批次分析的 watchlist 子集（分片请求时使用）")
    shard_size: int = Field(default=8, description="watchlist 内部分片大小，0 表示不分片")
    core_only: bool = Field(default=False, description="为 True 时只分析 priority shard（P1+持仓）")
    # ... rest unchanged ...
```

- [ ] **Step 2: Verify schema validation**

Run:

```bash
cd /home/ubuntu/learning-investment-strategies
.venv/bin/python -c "
from qing_investment.agent.models.schemas import TriggerRequest
r = TriggerRequest(trigger={'id': 'morning_confirm'})
assert r.shard_size == 8
assert r.core_only is False
print('schema OK')
"
```

Expected: `schema OK`.

- [ ] **Step 3: Commit**

```bash
git add src/qing_investment/agent/models/schemas.py
git commit -m "feat(agent): expose shard_size and core_only in TriggerRequest"
```

---

## Task 3: Pass shard controls into AgentState

**Files:**
- Modify: `src/qing_investment/agent/main.py`

**Interfaces:**
- Consumes: `TriggerRequest.shard_size`, `TriggerRequest.core_only`.
- Produces: initial `AgentState["shard_size"]`, `AgentState["core_only"]`.

- [ ] **Step 1: Populate the state dict**

In `src/qing_investment/agent/main.py`, inside `analyze_trigger`, add `shard_size` and `core_only` to the `state` dict initialized at lines 173-206:

```python
state = {
    # ... existing keys ...
    "watchlist_shard": req.watchlist_shard,
    "sector_strengths": req.sector_strengths,
    # Add these two:
    "shard_size": req.shard_size if req.shard_size > 0 else 8,
    "core_only": req.core_only,
    # ... rest unchanged ...
}
```

- [ ] **Step 2: Verify state construction**

Run:

```bash
cd /home/ubuntu/learning-investment-strategies
.venv/bin/python -c "
from qing_investment.agent.models.schemas import TriggerRequest
req = TriggerRequest(trigger={'id': 'morning_confirm'}, shard_size=4, core_only=True)
state = {
    'shard_size': req.shard_size if req.shard_size > 0 else 8,
    'core_only': req.core_only,
}
assert state['shard_size'] == 4
assert state['core_only'] is True
print('state construction OK')
"
```

Expected: `state construction OK`.

- [ ] **Step 3: Commit**

```bash
git add src/qing_investment/agent/main.py
git commit -m "feat(agent): pass shard_size and core_only from TriggerRequest into AgentState"
```

---

## Task 4: Add shard_router node

**Files:**
- Modify: `src/qing_investment/agent/graph/nodes.py`
- Test: `tests/test_qing_agent_monitor_workflow.py`

**Interfaces:**
- Consumes: `AgentState["watchlist"]`, `AgentState["positions"]`, `AgentState["shard_size"]`, `AgentState["core_only"]`.
- Produces: `list[Send]` targeting `"stock_scanner_shard"`, each carrying `{"watchlist_shard": <shard_context>}`.

- [ ] **Step 1: Add imports**

At the top of `src/qing_investment/agent/graph/nodes.py`, add:

```python
import os
from langgraph.constants import Send
```

- [ ] **Step 2: Implement shard_router**

Add the following function near the other router/helper functions (e.g., after `_load_analysis_framework`):

```python
def shard_router(state: AgentState) -> list[Send]:
    """根据 watchlist 生成分片，并 fan-out 到多个 stock_scanner_shard 节点。

    当 shard_size <= 0 或 watchlist 很小时，返回单个 shard（复用现有逻辑，不走外部分片）。
    """
    from qing_investment.agent.tools.watchlist_sharder import (
        shard_watchlist,
        shard_to_context,
    )

    watchlist = _normalize_watchlist(state.get("watchlist"))
    positions = _normalize_positions(state.get("positions"))

    # 兼容旧的外部分片请求：如果调用方已经传了 watchlist_shard，直接用它
    existing_shard = state.get("watchlist_shard")
    if existing_shard:
        return [Send("stock_scanner_shard", {"watchlist_shard": existing_shard})]

    shard_size = state.get("shard_size") or int(
        os.environ.get("WATCHLIST_SHARD_SIZE", "8")
    )
    core_only = state.get("core_only", False)

    shards = shard_watchlist(
        watchlist,
        positions,
        max_items=shard_size,
        core_only=core_only,
    )

    if not shards:
        # 没有可分析标的时仍跑一个空 shard，保证下游节点有 market_context
        return [Send("stock_scanner_shard", {"watchlist_shard": None})]

    return [
        Send("stock_scanner_shard", {"watchlist_shard": shard_to_context(s)})
        for s in shards
    ]
```

- [ ] **Step 3: Write a focused unit test for shard_router**

Create `tests/test_shard_router.py`:

```python
from qing_investment.agent.graph.nodes import shard_router


def test_shard_router_fan_out():
    state = {
        "watchlist": [
            {"code": "000001.SZ", "name": "A", "theme": "t1"},
            {"code": "000002.SZ", "name": "B", "theme": "t1"},
            {"code": "000003.SZ", "name": "C", "theme": "t2"},
        ],
        "positions": [],
        "shard_size": 2,
        "core_only": False,
    }
    sends = shard_router(state)
    assert len(sends) >= 2
    for s in sends:
        assert s.node == "stock_scanner_shard"
        assert "watchlist_shard" in s.arg
```

Run:

```bash
cd /home/ubuntu/learning-investment-strategies
.venv/bin/python -m pytest tests/test_shard_router.py -v
```

Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add src/qing_investment/agent/graph/nodes.py tests/test_shard_router.py
git commit -m "feat(agent): add shard_router node for internal watchlist fan-out"
```

---

## Task 5: Convert stock_scanner into a parallel shard node

**Files:**
- Modify: `src/qing_investment/agent/graph/nodes.py`
- Test: `tests/test_qing_agent_monitor_workflow.py`

**Interfaces:**
- Consumes: `AgentState["watchlist_shard"]`, `AgentState["market_summary_context"]`.
- Produces: `{"stock_scanner_results": [<single-result-dict>]}` where each result has the same shape as the old `stock_scanner` return value.

- [ ] **Step 1: Rename the existing function and change its return shape**

Rename `stock_scanner` → `stock_scanner_shard`. Keep all internal logic, but change the final `return` block (lines 2250-2256) so it wraps the result in a list:

```python
def stock_scanner_shard(state: AgentState) -> AgentState:
    """个股扫描节点（分片版）：基于市场背景扫描单个 watchlist shard。"""
    # ... all existing body of stock_scanner remains ...

    return {
        "stock_scanner_results": [
            {
                "market_context": full_market_context,
                "reasoning_steps": [
                    f"个股扫描({shard_name}): opportunities={len(full_market_context.get('opportunity_scan', []))} positions={len(full_market_context.get('position_plans', []))}"
                ],
                "cost_tracking": [_ss_cost],
            }
        ],
    }
```

Specifically, replace the current final return in `stock_scanner`:

```python
return {
    "market_context": full_market_context,
    "reasoning_steps": [
        f"个股扫描: opportunities={len(full_market_context.get('opportunity_scan', []))} positions={len(full_market_context.get('position_plans', []))}"
    ],
    "cost_tracking": [_ss_cost],
}
```

with the wrapped version above.

- [ ] **Step 2: Remove the internal bisect fallback**

Delete lines 2127-2161 (the `if prompt_bytes > _MAX_STOCK_SCANNER_PROMPT_BYTES:` bisect block inside the function). The graph-level fan-out now handles oversized prompts.

After deletion, the block should read:

```python
    if prompt_bytes > _MAX_STOCK_SCANNER_PROMPT_BYTES:
        logger.error(
            "stock_scanner prompt still exceeds %d bytes (%d bytes) after truncation; returning degraded context without LLM call",
            _MAX_STOCK_SCANNER_PROMPT_BYTES, prompt_bytes,
        )
        full_market_context = dict(market_summary_ctx)
        # ... rest of degraded fallback unchanged ...
```

- [ ] **Step 3: Adjust daily_state persistence**

Move daily_state persistence out of `stock_scanner_shard` and into `merge_scanner_results` (Task 6). In `stock_scanner_shard`, keep the extraction of `daily_state` blocks but do not call `_persist_daily_state_from_market_context`. Comment out or remove the persistence block (lines 2234-2248):

```python
    # 提取 daily_state 代码块，留给 merge_scanner_results 统一持久化
    scanner_override = _extract_daily_state_block(content)
    # 注意：不要在分片节点单独持久化，避免多个并行节点写 daily_state 冲突
```

- [ ] **Step 4: Verify the node runs in isolation**

Run:

```bash
cd /home/ubuntu/learning-investment-strategies
.venv/bin/python -c "
from qing_investment.agent.graph.nodes import stock_scanner_shard
print('stock_scanner_shard import OK')
"
```

Expected: `stock_scanner_shard import OK`.

- [ ] **Step 5: Commit**

```bash
git add src/qing_investment/agent/graph/nodes.py
git commit -m "feat(agent): convert stock_scanner to parallel stock_scanner_shard node"
```

---

## Task 6: Add merge_scanner_results node

**Files:**
- Modify: `src/qing_investment/agent/graph/nodes.py`
- Test: `tests/test_qing_agent_monitor_workflow.py`

**Interfaces:**
- Consumes: `AgentState["stock_scanner_results"]`, `AgentState["market_summary_context"]`, `AgentState["trigger"]`, `AgentState["parsed_intent"]`.
- Produces: `{"market_context": <merged>, "reasoning_steps": [...], "cost_tracking": [...]}`.

- [ ] **Step 1: Implement merge_scanner_results**

Add the following function after `stock_scanner_shard`:

```python
def merge_scanner_results(state: AgentState) -> AgentState:
    """合并多个 stock_scanner_shard 的输出，统一生成 market_context 并持久化 daily_state。"""
    logger = logging.getLogger(__name__)
    results = state.get("stock_scanner_results", []) or []
    market_summary_ctx = state.get("market_summary_context") or {}
    trigger_id = (state.get("trigger") or {}).get("id")
    analysis_type = (state.get("parsed_intent") or {}).get("analysis_type", "stock")

    merged = dict(market_summary_ctx)
    merged.setdefault("opportunity_scan", [])
    merged.setdefault("position_plans", [])

    reasoning_steps: list[str] = []
    total_cost: list[dict] = []
    any_truncated = False
    any_failed = False

    for idx, r in enumerate(results):
        mc = r.get("market_context", {}) if isinstance(r, dict) else {}
        reasoning_steps.extend(r.get("reasoning_steps", []) if isinstance(r, dict) else [])
        total_cost.extend(r.get("cost_tracking", []) if isinstance(r, dict) else [])
        any_truncated = any_truncated or bool(mc.get("_truncated"))
        any_failed = any_failed or bool(mc.get("_scan_failed"))

        for opp in mc.get("opportunity_scan", []):
            merged["opportunity_scan"].append(opp)
        for plan in mc.get("position_plans", []):
            merged["position_plans"].append(plan)

    if any_truncated:
        merged["_truncated"] = True
    if any_failed:
        merged["_scan_failed"] = True

    # 统一持久化 daily_state（一次触发只写一次）
    source_tag = f"stock_scanner:{analysis_type}"
    _persist_daily_state_from_market_context(merged, None, source_tag, trigger_id)

    logger.info(
        "merge_scanner_results: shards=%d opportunities=%d position_plans=%d",
        len(results),
        len(merged.get("opportunity_scan", [])),
        len(merged.get("position_plans", [])),
    )

    return {
        "market_context": merged,
        "reasoning_steps": [
            f"个股扫描合并: {len(results)} 个分片, opportunities={len(merged.get('opportunity_scan', []))}, position_plans={len(merged.get('position_plans', []))}"
        ] + reasoning_steps,
        "cost_tracking": total_cost,
        # 清空累加器，避免后续节点误用旧数据
        "stock_scanner_results": [],
    }
```

- [ ] **Step 2: Add a focused unit test**

Create `tests/test_merge_scanner_results.py`:

```python
from qing_investment.agent.graph.nodes import merge_scanner_results


def test_merge_combines_opportunities_and_plans():
    state = {
        "stock_scanner_results": [
            {
                "market_context": {
                    "opportunity_scan": [{"code": "000001", "name": "A"}],
                    "position_plans": [{"code": "000001", "action": "hold"}],
                },
                "reasoning_steps": ["shard-A"],
                "cost_tracking": [{"llm_calls": 1, "total_cost_usd": "0.01"}],
            },
            {
                "market_context": {
                    "opportunity_scan": [{"code": "000002", "name": "B"}],
                    "position_plans": [],
                },
                "reasoning_steps": ["shard-B"],
                "cost_tracking": [{"llm_calls": 1, "total_cost_usd": "0.01"}],
            },
        ],
        "market_summary_context": {"market_phase": "磨底期"},
        "trigger": {"id": "morning_confirm"},
        "parsed_intent": {"analysis_type": "market"},
    }
    result = merge_scanner_results(state)
    mc = result["market_context"]
    assert len(mc["opportunity_scan"]) == 2
    assert len(mc["position_plans"]) == 1
    assert result["stock_scanner_results"] == []
```

Run:

```bash
cd /home/ubuntu/learning-investment-strategies
.venv/bin/python -m pytest tests/test_merge_scanner_results.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add src/qing_investment/agent/graph/nodes.py tests/test_merge_scanner_results.py
git commit -m "feat(agent): add merge_scanner_results node for fan-in"
```

---

## Task 7: Wire parallel scanner into the graph

**Files:**
- Modify: `src/qing_investment/agent/graph/builder.py`
- Test: `tests/test_qing_agent_monitor_workflow.py`

**Interfaces:**
- Consumes: `shard_router`, `stock_scanner_shard`, `merge_scanner_results` from `nodes.py`.
- Produces: compiled graph where `market_summary` fans out to parallel `stock_scanner_shard` nodes.

- [ ] **Step 1: Update imports and node registration**

In `src/qing_investment/agent/graph/builder.py`:

```python
from langgraph.constants import Send  # add this import

from .nodes import (
    citation_validator,
    devils_advocate,
    market_summary,
    merge_scanner_results,      # add
    parse_query,
    retrieve_knowledge,
    review_router,
    reviewer,
    shard_router,               # add
    stock_analyst,
    stock_scanner_shard,        # rename from stock_scanner
    style_writer,
    synthesize,
)
```

- [ ] **Step 2: Replace stock_scanner with the new topology**

Replace the existing edges around `market_summary`, `stock_scanner`, and `devils_advocate` with:

```python
    builder.add_node("shard_router", shard_router)
    builder.add_node("stock_scanner_shard", stock_scanner_shard)
    builder.add_node("merge_scanner_results", merge_scanner_results)

    # ... existing nodes ...

    builder.set_entry_point("parse_query")
    builder.add_edge("parse_query", "retrieve_knowledge")
    builder.add_edge("retrieve_knowledge", "market_summary")
    builder.add_edge("retrieve_knowledge", "stock_analyst")

    # market_summary 后内部分片并行扫描
    builder.add_edge("market_summary", "shard_router")
    builder.add_conditional_edges(
        "shard_router",
        shard_router,
        ["stock_scanner_shard"],
    )
    builder.add_edge("stock_scanner_shard", "merge_scanner_results")
    builder.add_edge("merge_scanner_results", "devils_advocate")

    builder.add_edge("stock_analyst", "devils_advocate")
    builder.add_edge("devils_advocate", "synthesize")
    # ... rest unchanged ...
```

Also update the topology log line at the top of `build_graph()`:

```python
logger.info("[build_graph] topology: parse_query → retrieve_knowledge → (market_summary → shard_router → [stock_scanner_shard] → merge_scanner_results) + stock_analyst → devils_advocate → synthesize → style_writer → citation_validator → reviewer → END")
```

- [ ] **Step 3: Verify graph compiles**

Run:

```bash
cd /home/ubuntu/learning-investment-strategies
.venv/bin/python -c "
from qing_investment.agent.graph.builder import build_graph
g = build_graph()
print('nodes:', list(g.nodes))
"
```

Expected: `nodes:` includes `shard_router`, `stock_scanner_shard`, `merge_scanner_results` and no `stock_scanner`.

- [ ] **Step 4: Commit**

```bash
git add src/qing_investment/agent/graph/builder.py
git commit -m "feat(agent): wire internal parallel stock_scanner shards into graph"
```

---

## Task 8: Simplify external cron script

**Files:**
- Modify: `scripts/hermes_stock_monitor_agent.py`
- Test: run the script in dry mode or with mock quotes.

**Interfaces:**
- Consumes: `TriggerRequest.shard_size`, `TriggerRequest.core_only`.
- Produces: single POST to `/analyze/trigger`.

- [ ] **Step 1: Remove external sharding imports and helpers**

In `scripts/hermes_stock_monitor_agent.py`:

1. Remove the import of `watchlist_sharder`:

```python
# DELETE this line:
from qing_investment.agent.tools.watchlist_sharder import shard_watchlist, shard_to_context
```

2. Remove `SHARDABLE_TRIGGER_IDS`, `WATCHLIST_SHARD_SIZE`, `WATCHLIST_CORE_ONLY`, `_aggregate_sharded_responses`.

3. Keep `QING_AGENT_TIMEOUT`, `QING_AGENT_MAX_RETRIES`, request logging, fallback, etc.

- [ ] **Step 2: Rewrite call_qing_agent**

Replace `call_qing_agent` with:

```python
def call_qing_agent(data: dict) -> dict | None:
    """POST the context dict to qing-agent and return the response JSON."""
    if not _wait_for_agent_health(QING_AGENT_HEALTH_URL, max_wait_s=60):
        print("[qing-agent] agent not ready (cold start?), falling back", file=sys.stderr)
        return None

    market_snapshot, quote_lookup = _build_market_snapshot(data)

    payload = {
        "query": f"{data.get('trigger', {}).get('title', '')}：{data.get('trigger', {}).get('reason', '')}",
        "session_id": f"hermes-{data.get('timestamp', 'now')}",
        "stock_code": data.get("stock_code", ""),
        "analysis_type": data.get("analysis_type", "market"),
        "trigger": data.get("trigger", {}),
        "alerts": data.get("alerts", []),
        "buy_signal_candidates": data.get("buy_signal_candidates", []),
        "market_snapshot": market_snapshot,
        "positions": _normalize_positions(data.get("positions", {}), quote_lookup),
        "watchlist": _normalize_watchlist(data.get("watchlist", []), quote_lookup),
        "sector_strengths": data.get("sector_strengths", []),
        "external_sector_boards": data.get("external_sector_boards", {}),
        "shard_size": int(os.environ.get("WATCHLIST_SHARD_SIZE", "8")),
        "core_only": os.environ.get("WATCHLIST_CORE_ONLY", "0").lower() in ("1", "true", "yes", "on"),
    }

    trigger_id = (data.get("trigger") or {}).get("id", "")
    post_timeout = 90.0 if trigger_id == "pre_market" else None
    response = _post_analyze_trigger(payload, timeout=post_timeout)
    _log_request_payload(
        data,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        response,
        error=None,
        elapsed_ms=None,
    )

    if trigger_id == "pre_market" and response is None:
        try:
            ds = load_daily_state()
            ds["pre_market_brief"] = {"available": False, "errors": ["pre_market 节点调用超时或失败"]}
            ds = update_market_stage(
                ds,
                phase="数据不可用",
                detail="09:00 节点超时",
                updated_by="pre_market:timeout",
            )
            save_daily_state(ds)
        except Exception as e:
            print(f"[pre_market] failed to save degraded state: {e}", file=sys.stderr)

    return response
```

- [ ] **Step 3: Verify script imports**

Run:

```bash
cd /home/ubuntu/learning-investment-strategies
.venv/bin/python -c "
import sys
sys.path.insert(0, 'src')
from scripts.hermes_stock_monitor_agent import call_qing_agent
print('cron script import OK')
"
```

Expected: `cron script import OK`.

- [ ] **Step 4: Commit**

```bash
git add scripts/hermes_stock_monitor_agent.py
git commit -m "feat(cron): move watchlist sharding into qing-agent, call analyze_trigger once"
```

---

## Task 9: Update end-to-end workflow test

**Files:**
- Modify: `tests/test_qing_agent_monitor_workflow.py`

**Interfaces:**
- Consumes: updated graph topology with `shard_router`/`stock_scanner_shard`/`merge_scanner_results`.
- Produces: passing tests validating the new internal fan-out/fan-in path.

- [ ] **Step 1: Update fake LLM responses for shard prompts**

The `_FakeLangChainLLM._response_for` method currently keys on `"【任务】"` and `"opportunity_scan"` for the stock scanner. After the change, the prompt still contains `opportunity_scan` and the same template text, so this branch should still match. Verify by running the test first.

- [ ] **Step 2: Add a multi-shard workflow test**

Append to `tests/test_qing_agent_monitor_workflow.py`:

```python
def test_qing_agent_internal_sharding(monkeypatch, tmp_path):
    """验证 watchlist 超过 shard_size 时，graph 内部走分片并行扫描。"""
    monkeypatch.setenv("QING_AGENT_MOCK_QUOTES", "1")
    monkeypatch.setenv("QING_AGENT_IGNORE_TRADING_TIME", "1")
    monkeypatch.setenv("KIMI_CODE_ACP_FIRST", "0")
    monkeypatch.setenv("KIMI_CODE_CLI_FIRST", "0")

    config = make_mock_monitor_config()
    # 扩展观察池到 3 只，shard_size=1 强制分片
    config.watchlist["themes"].append({
        "id": "other",
        "name": "其他",
        "stocks": [
            {"code": "000002.SZ", "name": "万科A", "watch_reason": "测试"},
            {"code": "000063.SZ", "name": "中兴通讯", "watch_reason": "测试"},
        ],
    })

    agent_json_text = run_tick(
        config,
        datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        agent_json_context=True,
        state_path=tmp_path / "state.json",
    )
    assert agent_json_text
    agent_json = json.loads(agent_json_text)

    query = agent_json["trigger"]["title"] + "：" + agent_json["trigger"]["reason"]
    state = _build_agent_state(agent_json, query)
    state["shard_size"] = 1
    state["core_only"] = False

    async def fake_retrieve_knowledge(state_in: dict) -> dict:
        return {
            "claims": [],
            "wiki_snippets": [],
            "knowledge_graph": {},
            "memories": [],
            "few_shot_examples": [],
        }

    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes.retrieve_knowledge", fake_retrieve_knowledge
    )
    import qing_investment.agent.graph.builder as builder_module
    monkeypatch.setattr(builder_module, "retrieve_knowledge", fake_retrieve_knowledge)

    fake_llm = _FakeLangChainLLM()
    monkeypatch.setattr(
        "qing_investment.agent.tools.llm_client.get_llm_client",
        lambda provider=None: fake_llm,
    )
    import qing_investment.agent.graph.nodes as nodes_module
    monkeypatch.setattr(nodes_module, "get_llm_client", lambda provider=None: fake_llm)

    import qing_investment.agent.agents.devils_advocate as da_module

    class _FakeDevilsAdvocateResult:
        findings = [{"target": "mock", "point": "mock finding"}]
        errors = []
        cost_usd = 0.0

    class _FakeDevilsAdvocateAgent:
        def __init__(self, llm=None):
            pass

        async def run(self, **kwargs):
            return _FakeDevilsAdvocateResult()

    monkeypatch.setattr(da_module, "DevilsAdvocateAgent", _FakeDevilsAdvocateAgent)

    import asyncio
    from qing_investment.agent.graph.builder import build_graph

    graph = build_graph()
    result = asyncio.run(graph.ainvoke(state))

    assert result["final_output"]
    assert result.get("review_passed") is True
    # 至少调用了 market_summary + 多个 stock_scanner_shard + style + reviewer
    assert len(fake_llm.calls) >= 5
```

- [ ] **Step 3: Run the updated tests**

```bash
cd /home/ubuntu/learning-investment-strategies
.venv/bin/python -m pytest tests/test_qing_agent_monitor_workflow.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_qing_agent_monitor_workflow.py
git commit -m "test(agent): update workflow tests for internal watchlist sharding"
```

---

## Self-Review

### Spec coverage

| Requirement | Task |
| --- | --- |
| Move sharding from external cron to qing-agent internal | Task 4, 5, 6, 7, 8 |
| Run `retrieve_knowledge` and `market_summary` once per trigger | Task 7 topology ensures single path before fan-out |
| Parallel per-sector/per-shard analysis | Task 4 (`shard_router`) + Task 5 (`stock_scanner_shard`) |
| Merge results before downstream nodes | Task 6 (`merge_scanner_results`) |
| Keep external env vars (`WATCHLIST_SHARD_SIZE`, `WATCHLIST_CORE_ONLY`) | Task 8 reads them and passes via payload |
| Preserve single-stock `/chat` and `stock_analyst` path | `stock_analyst` edge unchanged in Task 7 |
| Avoid duplicate `daily_state` writes | Task 5 removes per-shard persistence; Task 6 does it once |

### Placeholder scan

- No "TBD", "TODO", "implement later", or "fill in details".
- No vague steps like "add appropriate error handling".
- All code blocks contain concrete file paths, function names, and expected values.

### Type consistency

- `shard_router` returns `list[Send]` and uses `Send("stock_scanner_shard", {"watchlist_shard": ...})`.
- `stock_scanner_shard` returns `{"stock_scanner_results": [dict]}` matching `Annotated[list[dict], operator.add]`.
- `merge_scanner_results` consumes that list and produces `{"market_context": dict, ...}`.
- `TriggerRequest` exposes `shard_size: int` and `core_only: bool`, mirrored in `AgentState`.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-15-internal-watchlist-sharding.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints for review.

**Which approach?**
