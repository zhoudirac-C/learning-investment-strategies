# Poll 买入候选检测 — 字段读取路径

## 数据源优先级（从高到低）

```
1. strategy_pack.entry_points[].entry_zone      → parse_price_zone → (low, high)
2. positions.accounts[].positions[].add_zone     → parse_price_zone → (low, high)
3. watchlist.themes[].stocks[].entry_zone.price_range  → parse_price_zone → (low, high)
```

## 6 条件评估

poll 对每只票计算以下条件，≥4 满足 = 买入候选：

| # | 条件 | 数据源 | 阈值 |
|---|------|--------|------|
| 1 | 价格在介入区间 | 实时行情 vs price_range | `zone[0] ≤ latest ≤ zone[1]` |
| 2 | 非崩盘 | 实时行情 pct_change | `> -3.0%` |
| 3 | 未涨停 | 实时行情 pct_change | `< 7.0%` |
| 4 | UP明确看好 | entry.claim_basis 非空 | `bool(claim_basis)` |
| 5 | 近3日缩量 | SQLite K线 cache volume | `vol_3 < vol_2 < vol_1`（递减） |
| 6 | MA20上方 | SQLite K线 cache close vs MA20 | `close > ma20` |

## ⚠️ 陷阱：写入者和读取者用不同字段

**反面案例（2026-06-11）**：poll 读 `stock["buy_setup"]`，但 watchlist 写入者写的是 `stock["entry_zone"]["price_range"]`。→ parse_price_zone("") → None → 静默跳过。

**修复**：`stock_monitor.py:407-409` 从 `stock.get("buy_setup")` 改为 `stock.get("entry_zone", {}).get("price_range")`。

**规则**：
- `entry_zone.price_range` = 唯一的介入区间字段（数字格式 `"低~高"`）
- `buy_setup` = 仅买入条件补充说明文本，poll 不再从中提取数字
- P3-观察标的：`price_range: null`（即使有数字也不写，代码不读注释）
