# dedupe_by_type 代码实现（2026-06-04）

## 概述

`strategy_pack.yaml` 中 `notification_policy.dedupe_by_type` 配置的差异化去重逻辑已由 `stock_monitor.py` 实现并测试通过。

## 映射规则

`_action_to_dedupe_type(action)` 函数将 alert action 映射为 dedupe type：

| Alert action 包含 | 映射类型 | 默认去重 | 价格突破阈值 |
|-------------------|---------|---------|-------------|
| "风控"/"风险" | `risk_alert` | 15 min | 1.0% |
| "减仓" | `reduce_alert` | 30 min | 2.0% |
| "进攻"/"防御"/"指数"/"回流"/"轮动"/"板块" | `sector_rotation` | 30 min | 0%（不突破） |
| 其他 | `default` | 回退全局 `dedupe_minutes` | 0%（不突破） |

## 代码改动

1. **新增 `_action_to_dedupe_type(action)`** — action→type 映射函数
2. **修改 `filter_new_alerts()`** — 接受 `dedupe_by_type` 参数，对每个 alert 按类型查配置，支持价格突破逻辑
3. **修改 `record_emitted_alerts()`** — 存储 `{time, price}` 字典而非纯 ISO 字符串（支持突破价格判断）
4. **修改 `run_tick()`** — 从 `config.strategy_pack.notification_policy.dedupe_by_type` 读取配置并传递

## 价格突破逻辑（breakthrough_if_price_change_pct）

当去重窗口未满但价格变化达到阈值时，突破去重立即重新提醒：

```python
if breakthrough_pct > 0 and last_price is not None and last_price > 0:
    pct_change = abs((alert.price - last_price) / last_price) * 100
    if pct_change >= breakthrough_pct:
        fresh.append(alert)  # 突破去重！
```

## 向后兼容

- `state.json` 中旧格式（纯 ISO 字符串时间戳）被 `filter_new_alerts()` 正确读取
- `record_emitted_alerts()` 新格式向下兼容：存储 `{"time": "2026-06-04T10:00:00+08:00", "price": 35.0}`

## 验证

7 个新增单元测试覆盖：
- `test_action_to_dedupe_type_mapping` — 映射逻辑
- `test_dedupe_by_type_overrides_global_dedupe_minutes` — 差异化去重窗口
- `test_dedupe_by_type_breakthrough_triggers_on_price_change` — 价格突破
- `test_dedupe_by_type_breakthrough_suppressed_when_price_stable` — 价格稳定不去重
- `test_dedupe_by_type_falls_back_to_global_when_missing` — 全局回退
- `test_dedupe_by_type_backward_compat_with_old_string_format` — 旧格式兼容
- `test_tick_passes_dedupe_by_type_from_config` — run_tick 集成

全部 49 个测试通过。

## 已知修复：same-day dedupe 使用全局超时而非 per-type

**发现时间**：2026-06-10  
**测试**：`test_dedupe_by_type_overrides_global_dedupe_minutes`

### 症状

设置 risk_alert 去重 15min、全局 30min。第 20min 的 alert 应该通过（20 ≥ 15 类型窗口），但仍被拦截。

### 根因

`filter_new_alerts()` 的 same-day dedupe 块在比较时间间隔时使用了全局 `dedupe_minutes`（30min）而非 per-type 的 `effective_minutes`（15min）：

```python
# 修复前
if elapsed_minutes < dedupe_minutes:  # ← 全局 30min
    continue  # → 错误拦截

# 修复后
# per-type effective_minutes 计算提前到 same-day dedupe 之前
effective_minutes = type_config.get("dedupe_minutes", dedupe_minutes)
if elapsed_minutes < effective_minutes:  # ← per-type 15min
    continue
```

### 影响

只有设置了 `dedupe_by_type` 且类型窗口 < 全局窗口的场景触发。全局 30min + risk_alert 15min 时，15-30min 之间的 alert 被错误拦截。

### 修复

1. 将 `dedupe_type / type_config / effective_minutes` 计算提前到 same-day dedupe 块之前
2. `effective_minutes` 同时被 same-day dedupe 和 history-based dedupe 使用（移除重复计算）
3. 涉及文件：`src/qing_investment/stock_monitor.py` 的 `filter_new_alerts()`
