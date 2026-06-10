# 实时数据降级模式（Real-time Data Degradation Pattern）

> 当 Qing-Agent 的实时行情数据源不可用时，如何从"硬拒绝"降级为"知识库分析"。

---

## 问题场景

Cron job 在以下情况频繁失败：
- 数据源限流（腾讯/东财 API 返回 403/429）
- 网络波动导致行情获取超时
- 非交易时间运行但 `ignore_trading_time=False`

旧行为：`market_analyst` 节点检测到无实时数据 → 直接 return 空结果 → cron 输出"数据不可用"或无输出。

---

## 解决方案：三级降级

### Level 1: 实时数据正常
- `market_snapshot.quotes` 有数据
- `external_sector_boards.available = True`
- 正常分析，实时数据为主要依据

### Level 2: 实时数据缺失，知识库可用
- `market_snapshot.quotes` 为空或 `external_sector_boards.available = False`
- 设置 `state["_data_missing_note"]` 降级说明
- LLM 基于 claims + wiki + framework 做分析
- 输出明确标注"缺少实时价格验证"

### Level 3: 知识库也缺失
- 极少发生（claims 库通常有数据）
- LLM 基于通用框架做分析
- 输出"基于通用框架，无具体观点支撑"

---

## 代码修改清单

### 1. `src/qing_investment/agent/graph/nodes.py`

**位置**: `market_analyst()` 函数，约第 960-984 行

**修改前**:
```python
if analysis_type in ("market", "portfolio") and not has_realtime_data:
    return {
        "market_context": {
            "market_phase": "数据不可用",
            "phase_reasoning": "缺少实时行情数据...",
            # ... 空结果 ...
        },
        "reasoning_steps": ["market_analyst: 实时数据不可用，拒绝生成分析"],
    }
```

**修改后**:
```python
if analysis_type in ("market", "portfolio") and not has_realtime_data:
    state["_data_missing_note"] = (
        "【注意】实时行情数据暂时无法获取（数据源限流或网络问题）。"
        "本次分析将基于 UP 历史观点（claims）和策略框架进行，"
        "缺少实时价格验证，分析结论的时效性可能受限。"
    )
    # 继续执行，不中断
```

### 2. `src/qing_investment/agent/graph/state.py`

**新增字段**:
```python
class AgentState(TypedDict, total=False):
    # ... existing fields ...
    _data_missing_note: str     # 实时数据缺失时的降级说明
```

### 3. `src/qing_investment/agent/graph/nodes.py` (prompt 注入)

**位置**: `market_analyst()` 函数 prompt 构建处，约第 1064 行

**修改**:
```python
prompt = f"""{prompt_template_filled}

{state.get("_data_missing_note", "")}

检索到的知识（已过滤，仅保留方法论内容）：
..."""
```

### 4. `src/qing_investment/agent/models/schemas.py`

**新增字段**:
```python
class TriggerRequest(BaseModel):
    # ... existing fields ...
    analysis_type: str = Field(default="market", description="分析类型：market/stock/portfolio")
```

### 5. `src/qing_investment/agent/main.py`

**修改**:
```python
state = {
    # ... existing fields ...
    "parsed_intent": {"analysis_type": req.analysis_type},
}
```

### 6. `src/qing_investment/stock_monitor.py`

**位置**: `_agent_context_data()` 返回值

**新增**:
```python
return {
    # ... existing fields ...
    "market_snapshot": {
        "quotes": quote_snapshot.get("quotes", []),
        "source": quote_snapshot.get("source", "unknown"),
        "elapsed_ms": quote_snapshot.get("elapsed_ms", 0),
    },
    # ... rest of fields ...
}
```

---

## 验证命令

### 验证降级分析正常工作
```bash
curl -s --max-time 200 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"测试降级","session_id":"test-degradation","analysis_type":"market"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('final_output length:', len(d.get('final_output', ''))); print('Has output:', bool(d.get('final_output')))"
```

**期望**: `Has output: True`, `final_output length: > 500`

### 验证 market_snapshot 在 JSON 上下文中
```bash
cd ~/learning-investment-strategies
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import run_tick, load_monitor_config
from datetime import datetime
from zoneinfo import ZoneInfo
import json

config = load_monitor_config()
now = datetime.now(ZoneInfo('Asia/Shanghai'))
msg = run_tick(config=config, value=now, emit_status=False, ignore_trading_time=True, agent_json_context=True, agent_any_time=True)
data = json.loads(msg)
ctx = data.get('agent_analysis_context', {})
print('market_snapshot present:', bool(ctx.get('market_snapshot')))
if ctx.get('market_snapshot'):
    ms = ctx['market_snapshot']
    print('  quotes:', len(ms.get('quotes', [])))
    print('  source:', ms.get('source', 'N/A'))
"
```

**期望**: `market_snapshot present: True`, `quotes: 184`, `source: tencent_gtimg`

---

## 响应时间参考

| 场景 | 响应时间 |
|------|---------|
| 有实时数据 + 知识库 | 50-70s |
| 无实时数据 + 知识库（降级） | 55-85s |
| 完全无数据（极少） | 40-60s |

---

## 相关陷阱

- **陷阱**: `format_agent_json_context()` 返回的 JSON 中 `agent_analysis_context` 为空
  - 根因: `run_tick()` 返回的 JSON 结构可能不是 `{agent_analysis_context: {...}}`
  - 检查: 确认 `run_tick()` 返回的是 `_agent_context_data()` 的扁平结构还是嵌套结构
  - 修复: 调整 `scripts/hermes_stock_monitor_agent.py` 的调用逻辑

- **陷阱**: `market_snapshot` 在 `_agent_context_data()` 中有数据，但 cron 调用时缺失
  - 根因: `quote_snapshot` 参数传递问题，或 `run_tick()` 内部逻辑分支差异
  - 检查: 对比直接调用 `_agent_context_data()` vs `run_tick()` 的输出
