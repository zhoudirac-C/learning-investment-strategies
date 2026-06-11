# Poll 买入候选检测 — 字段读取路径

## 数据源优先级（从高到低）

```
第1层: strategy_pack.entry_points[]       → 优先读取
第2层: watchlist.themes[].stocks[]        → 仅当 code 不在 entry_points 时
第3层: positions.accounts[].positions[]   → 仅当 code 不在以上两层时
```

## 各层读取的字段

### 第1层: entry_points

| poll 读的字段 | entry_points 中的位置 |
|---|---|
| code | ep.code |
| name | ep.name |
| entry_zone | ep.entry_zone → parse_price_zone() |
| stop_loss | ep.stop_loss |
| claim_basis | ep.claim_basis — 条件4「UP看好」|

### 第2层: watchlist stocks（核心修复路径）

| poll 读的字段 | watchlist 中的位置 |
|---|---|
| code | stock.code |
| name | stock.name |
| entry_zone | stock.entry_zone.price_range → parse_price_zone() |
| stop_loss | stock.invalidation_setup |
| 注意 | 之前读到 stock.buy_setup，2026-06-11 已修复 |

### 第3层: positions

| poll 读的字段 | positions 中的位置 |
|---|---|
| code | pos.code |
| name | pos.name |
| entry_zone | pos.add_zone → parse_price_zone() |
| stop_loss | pos.risk_zone 或 pos.risk_line |

## parse_price_zone 行为

| 输入 | 输出 | 说明 |
|---|---|---|
| "118.0 ~ 122.0" | (118.0, 122.0) | 标准格式 |
| "118.0-122.0" | (118.0, 122.0) | 横杠分隔 |
| "118.0至122.0" | (118.0, 122.0) | 中文替换 |
| null | None | 空值 |
| "不设介入区间" | None | 无数字 |
| "48.0 ~ 50.0（仅供参考）" | (48.0, 50.0) | 注释被忽略 |

**关键**：parse_price_zone 只认数字，不读注释。任何含数字范围的字符串都会被解析。

## 6 项条件评分

```
价格进入区间    — 实时行情 vs entry_zone
非系统性大跌    — pct_change > -3.0
未涨停          — pct_change < 7.0
UP明确看好      — claim_basis 非空
近3日缩量       — SQLite K线 volume 递减
MA20上方        — SQLite K线 close > MA20

>=4 项满足 = 买入候选
```

## 常见错误（2026-06-11 修复清单）

1. **buy_setup 与 entry_zone.price_range 混淆**：已修复统一走后者
2. **P3-观察标的写数字区间 + 说明**：数字被 parse_price_zone 提取，说明被忽略
3. **price_range: "不设介入区间"**：正则找数字找不到 → None → 该票永远不被 poll 看到

## 验证命令

```bash
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import parse_price_zone
stock = {'entry_zone': {'price_range': '118.0 ~ 122.0'}}
ez = stock.get('entry_zone', {}) or {}
z = parse_price_zone(ez.get('price_range', ''))
assert z == (118.0, 122.0)
print('OK')
"
python scripts/validate_watchlist.py
```
