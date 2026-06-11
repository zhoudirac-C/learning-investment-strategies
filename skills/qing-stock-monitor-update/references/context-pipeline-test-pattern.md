# Context Pipeline 数据层验证模式

> 适用：验证数据层改动是否正确，不消耗 LLM token。
> 来源：2026-06-11 Phase 7.1-7.3 实施。

## 为什么需要数据层验证

LLM 验证（调用 qing-agent）每次 ~70-120s 且消耗 token。数据层验证可以在 5 秒内确认：
1. 数据字段完整（position_type、unrealized_pct 等）
2. 分类逻辑正确（weak_board vs limit_up 等）
3. 输出格式符合预期（模板结构调整）

## 验证脚本模板

```python
"""Context 数据层验证脚本"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qing_investment.stock_monitor import (
    format_agent_analysis_context, format_agent_json_context,
    _agent_context_data, _pure_stock_code,
    MonitorConfig, AgentAnalysisTrigger,
)

CN_TZ = timezone(timedelta(hours=8))

# ── 1. Mock Config ──
config = MagicMock(spec=MonitorConfig)
config.config_dir = Path("config/stock_monitor")
config.strategy_pack = {"market_framework": {"current_stage": "等修复", "core_question": "测试"}}
config.positions = {
    "accounts": [{
        "name": "主账户",
        "positions": [
            {"code": "002409", "name": "雅克科技", "cost": 23.5, "shares": 1000},
            {"code": "000636", "name": "风华高科", "cost": 32.0, "shares": 500},
        ],
    }],
}
config.watchlist = {"themes": []}

trigger = AgentAnalysisTrigger(
    kind="scheduled", id="mock", title="测试",
    reason="mock", dedupe_key="mock",
)

# ── 2. Mock Quote Snapshot ──
quote_snapshot = {
    "source": "mock", "elapsed_ms": 100,
    "quotes": [
        {"code": "002409", "name": "雅克科技",
         "latest": "22.5", "pct_change": "-4.3",
         "previous_close": "23.5", "open": "22.8",
         "high": "23.0", "low": "22.3", "volume": "50000"},
        {"code": "000636", "name": "风华高科",
         "latest": "33.5", "pct_change": "4.7",
         "previous_close": "32.0", "open": "32.5",
         "high": "33.8", "low": "32.2", "volume": "30000"},
    ],
    "errors": [],
}

# ── 3. 运行 ──
value = datetime(2026, 6, 12, 9, 45, tzinfo=CN_TZ)
data = _agent_context_data(config, value, trigger, [], quote_snapshot, {})

# ── 4. 验证点 ──
assert "positions" in data
for pos in data["positions"]:
    code = _pure_stock_code(str(pos.get("code", "")))
    assert pos.get("avg_cost") is not None, f"{code}: avg_cost 缺失"
    assert pos.get("unrealized_pct") is not None, f"{code}: unrealized_pct 缺失"
    assert pos.get("cost_protection_line") is not None, f"{code}: cost_protection_line 缺失"
    assert pos.get("position_type") in ("limit_up", "weak_board", "floating_loss", "trend")

# ── 5. 验证 text context 格式 ──
text = format_agent_analysis_context(config, value, trigger, [], quote_snapshot, {})
checks = {
    "新模板格式: 重点分析": "【重点分析】" in text,
    "新模板格式: 其他持仓": "【其他持仓】" in text,
    "新模板格式: 盘面无全A锚": "【全A锚】" not in text,
    "position_type 标签": "[trend]" in text or "[weak_board]" in text,
}
for label, ok in checks.items():
    assert ok, f"失败: {label}"

# ── 6. 验证 JSON context 字段 ──
json_str = format_agent_json_context(config, value, trigger, [], quote_snapshot, {})
parsed = json.loads(json_str)
assert "yesterday_summary" in parsed
assert "auction_snapshot" in parsed
assert all("position_type" in p for p in parsed.get("positions", []))

print(f"✅ 全部通过: {len(checks) + 6} 个断言")
```

## 验证维度

| 维度 | 检查内容 | 示例断言 |
|------|---------|---------|
| **数据结构** | 字段是否存在、类型是否正确 | `assert pos.get("avg_cost") is not None` |
| **分类逻辑** | 不同持仓是否正确分类 | `assert trend_pos["position_type"] == "trend"` |
| **Text 格式** | 模板段正确合并/拆分 | `assert "【全A锚】" not in text` |
| **JSON 字段** | 所有必填字段存在 | `assert "position_type" in p for p in positions` |
| **新模板指令** | LLM 输出约束正确 | `assert "每只15字" in text` |

## 范围

验证 context pipeline 只验证**数据层 + 模板层**，不验证 LLM 输出质量。LLM 输出验证需要：
1. qing-agent 在线（`/health` + `/analyze/trigger` 端点）
2. 非交易时段超时设置（`QING_AGENT_TIMEOUT ≥ 180s`）
3. 实盘观察（交易时段自然触发）
