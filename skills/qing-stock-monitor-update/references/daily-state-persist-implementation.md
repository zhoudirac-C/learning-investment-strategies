# daily_state 持久化实现细节

> 记录 2026-06-10 在 Qing-Agent `market_analyst` 节点中实现 daily_state 自动持久化的技术细节。
> 对应代码：`src/qing_investment/agent/graph/nodes.py`

## 背景

daily_state 链路存在两层断裂：
1. **Cron 层**：Qing-Agent 未启动 → fallback → Hermes 直接生成 → 无 daily_state 代码块
2. **Agent 内部**：`market_analyst` 节点只解析 JSON，丢弃 LLM 输出的 ````daily_state` 代码块

本修复聚焦第 2 层，在 Qing-Agent 内部闭环。

## 实现方案（方案 A）

在 `market_analyst` 节点 LLM 返回后、返回 state 前，插入 daily_state 提取和保存逻辑。

### 新增函数

#### `_extract_daily_state_block(content: str) -> dict | None`

从 LLM 原始输出（非解析后的 JSON）中用正则提取 ````daily_state` 代码块。

```python
pattern = re.compile(r"```daily_state\s*\n(.*?)```", re.DOTALL)
```

为什么从原始输出提取？因为 `json.loads()` 会丢弃代码块部分（JSON 解析器在遇到 ``` 之前就停止了）。

#### `_persist_daily_state_from_market_context(market_context, daily_state_override, source_tag)`

统一持久化入口，双源合并：

1. **优先使用 LLM 显式输出的 daily_state 块**（`daily_state_override`）
   - `market_stage` → `update_market_stage()`
   - `direction_priority` → `update_direction_priority()`
   - `position_stance` → `update_position_stance()`
   - `active_opportunities` → `add_opportunity()`（按 code 去重）
   - 各种 narrative 键（core_assumption、morning_summary 等 18 个）→ `add_intraday_narrative()`

2. **Fallback 从 `market_context` 规范化字段推导**
   - `market_phase` + `phase_reasoning` → market_stage
   - `main_themes` → direction_priority
   - `position_plans[0].position_advice` → position_stance
   - `opportunity_scan` → active_opportunities
   - `market_summary` → intraday_narrative

3. **元数据标记**
   - `_meta.last_persisted_by`
   - `_meta.last_persisted_at`

### 修改点

在 `market_analyst()` 函数末尾、return 之前：

```python
# 【新增】提取并持久化 daily_state
daily_state_override = _extract_daily_state_block(content)
source_tag = f"market_analyst:{analysis_type}"
_persist_daily_state_from_market_context(result, daily_state_override, source_tag)
```

### 依赖导入

```python
from qing_investment.agent.tools.daily_state import (
    load_daily_state, save_daily_state,
    update_market_stage, update_direction_priority,
    update_position_stance, add_opportunity, add_intraday_narrative,
)
```

## 验证

```bash
# 1. 直接测试 market_analyst 节点
cd ~/learning-investment-strategies
timeout 30 .venv/bin/python -c "
from qing_investment.agent.graph.nodes import market_analyst
state = {
    'parsed_intent': {'analysis_type': 'market'},
    'claims': [], 'wiki_snippets': [], 'positions': [], 'watchlist': [],
    'external_sector_boards': {'available': False},
    'market_snapshot': {'quotes': []},
}
result = market_analyst(state)
print('market_phase:', result['market_context'].get('market_phase'))
"

# 2. 检查 daily_state.json 是否生成
ls -la config/stock_monitor/daily_state.json

# 3. 检查内容结构
cat config/stock_monitor/daily_state.json | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('date:', d['date'])
print('market_stage:', d['market_stage']['phase'])
print('directions:', len(d['direction_priority']))
print('opportunities:', len(d['active_opportunities']))
print('narrative:', len(d['intraday_narrative']))
print('last_persisted_by:', d['_meta']['last_persisted_by'])
"
```

## 已知限制

1. **只覆盖 `market_analyst` 节点**：`stock_analyst` 节点（个股分析）未实现 daily_state 持久化。如果用户问个股，daily_state 不会更新。
2. **依赖 LLM 遵守 prompt**：`market_analyst.txt` 要求输出 ````daily_state`，但 LLM 可能省略。有 fallback 推导，但字段覆盖不完整。
3. **Qing-Agent 必须启动**：cron 层断裂（Qing-Agent 未启动）仍需单独解决——启动服务 + 确保 cron 调用走 Qing-Agent 路径。

## 后续可优化

1. 在 `stock_analyst` 节点也加入 daily_state 持久化（更新个股相关的 active_opportunities）
2. 在 graph 末尾增加独立的 `persist_daily_state` 节点，统一处理所有分析类型的 daily_state
3. 在 Hermes fallback 路径中也提取 daily_state（方案 B 补充）

## 相关文件

- `src/qing_investment/agent/graph/nodes.py` — 核心修改
- `src/qing_investment/agent/tools/daily_state.py` — 工具函数
- `src/qing_investment/agent/prompts/system/market_analyst.txt` — daily_state 输出要求
