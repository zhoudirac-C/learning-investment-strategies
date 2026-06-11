# Dragon/Tiger Board Data via akshare (东方财富接口)

## Overview

Dragon/tiger board (龙虎榜) data shows the TOP 5 buy/sell seats for stocks that meet exchange-mandated disclosure criteria (≥7% price move, consecutive boards, etc.). Available via akshare's 东方财富 backend.

## Available APIs

| Function | Purpose | Signature |
|----------|---------|-----------|
| `stock_lhb_stock_detail_em` | Individual stock detail | `(symbol="002409", date="20260611", flag="买入")` |
| `stock_lhb_stock_detail_date_em` | Available dates for a stock | `(symbol="002409")` |
| `stock_lhb_detail_em` | Daily market-wide summary | `(start_date="20260610", end_date="20260610")` |

## Data Availability Timing

Dragon/tiger board data is published by the exchange **after market close**, typically:
- Shanghai/Shenzhen main board: ~16:30-17:00
- ChiNext/STAR board: ~17:00-17:30

Between 15:00 and publication time, the API returns `None` — handle this with `if df_buy is None: return {"_error": "当日未上榜"}`. Do NOT crash or block on this.

## Individual Stock Detail (`stock_lhb_stock_detail_em`)

```python
import akshare as ak

df_buy = ak.stock_lhb_stock_detail_em(symbol="002409", date="20260611", flag="买入")
df_sell = ak.stock_lhb_stock_detail_em(symbol="002409", date="20260611", flag="卖出")
```

### Columns returned

```
序号 | 交易营业部名称 | 买入金额 | 买入金额-占总成交比例 | 卖出金额 | 卖出金额-占总成交比例 | 净额 | 类型
```

- `交易营业部名称` — the broker/seat name (key for classification)
- `买入金额` — buy amount (float, scientific notation e.g. 1.619302e+08)
- `卖出金额` — sell amount (float)
- `净额` — net buy-sell amount (float)
- `类型` — always the triggering condition ("日涨幅偏离值达到7%的前5只证券"), NOT seat type

### Error handling

```python
df_buy = ak.stock_lhb_stock_detail_em(...)
# ❌ Returns None for non-listed stocks (not an empty DataFrame!)
if df_buy is None:
    return {"_error": "当日未上榜"}
try:
    if df_buy.empty:
        return {"_error": "当日未上榜"}
except Exception:
    pass  # df_buy may be a dict-like, not DataFrame
```

## Daily Market Summary (`stock_lhb_detail_em`)

```python
df_summary = ak.stock_lhb_detail_em(start_date="20260610", end_date="20260610")
```

Columns include: 代码, 名称, 收盘价, 涨跌幅, 龙虎榜净买额, 龙虎榜买入额, 龙虎榜卖出额, 龙虎榜成交额, 市场总成交额, 换手率, 流通市值, 上榜原因, 上榜后涨幅 (1/2/5/10日)

## Seat Type Classification Keyword Map

```python
_SEAT_TYPE_KEYWORDS = {
    "深股通专用": "外资",       # Shenzhen-HK Stock Connect
    "沪股通专用": "外资",       # Shanghai-HK Stock Connect
    "机构专用": "机构",         # Institutional seat
    "中信证券股份有限公司": "游资",  # CITIC Securities
    "中国国际金融股份有限公司": "量化",  # CICC (quantitative)
    "量化": "量化",
}

def _classify_seat_type(name: str) -> str:
    for keyword, seat_type in _SEAT_TYPE_KEYWORDS.items():
        if keyword in name:
            return seat_type
    return "游资"  # default: hot money
```

### Known seat name patterns

| Pattern | Classification | Example |
|---------|---------------|---------|
| `深股通专用` / `沪股通专用` | 外资 | North-bound connect |
| `机构专用` | 机构 | Fund/insurance seat |
| `中国国际金融股份有限公司上海分公司` | 量化 | CICC quant desk |
| `中信证券股份有限公司深圳分公司` | 游资 | Broker hot money |
| `国盛证券股份有限公司杭州XX路` | 游资 | Regional broker |
| `国泰海通证券股份有限公司上海XX路` | 游资 | Major broker seat |
| `中泰证券股份有限公司天津XX路` | 游资 | Regional broker |

The keyword-matching approach works because most akshare names are full legal names — partial matching on "机构专用", "深股通", "中信证券", "中金" is sufficient and unlikely to false-positive.

## Top Buyer Behavior Classification

```python
def _classify_top_buy_behavior(df_buy, df_sell):
    top_buy_name = df_buy.iloc[0]["交易营业部名称"]
    top_buy_net = float(df_buy.iloc[0]["净额"])
    top_sell_net = float(df_sell.iloc[0]["净额"]) if not df_sell.empty else 0

    buy_names = set(df_buy["交易营业部名称"])
    sell_names = set(df_sell["交易营业部名称"])
    overlap = buy_names & sell_names

    if top_buy_name in overlap:            return "做T"   # day-trading
    if top_buy_net > abs(top_sell_net) * 3: return "锁仓"  # strong accumulation
    if top_buy_net > abs(top_sell_net) * 1.5: return "加仓"
    if top_buy_net < abs(top_sell_net) * 0.5: return "出局"
    return "混合"
```

### Behavior categories

| Category | Condition | Meaning |
|----------|-----------|---------|
| 锁仓 | 买一净额 > 3x 卖一净额 | Strong accumulation, likely to hold |
| 加仓 | 买一净额 > 1.5x 卖一净额 | Moderate buying |
| 做T | 买一出现在买卖双榜 | Day-trading, may exit tomorrow |
| 出局 | 买一净额 < 0.5x 卖一净额 | Weak hands, likely distribution |
| 混合 | 其他 | Unclear signal |

## Board Quality Assessment

```python
def _assess_board_quality(df_buy, df_sell):
    total_net = float(df_buy["净额"].sum())
    total_sell = float(df_sell["净额"].sum())
    net = total_net
    if net > 0 and net > abs(total_sell) * 2: return "strong"
    if net > 0: return "medium"
    return "weak"
```

| Quality | Meaning |
|---------|---------|
| strong | Net buying dominates; institutions present |
| medium | Mixed; some buying but also selling pressure |
| weak | Net selling or highly ambivalent |

## Full-Market Board Cross-Check (Phase 4.1b)

### Why the full-market board

The individual stock API (`stock_lhb_stock_detail_em`) only fetches data for limit-up positions. The full-market board (`stock_lhb_detail_em`) adds:

1. **Watchlist stocks on the board**: A watchlist stock may appear on the dragon/tiger board even though it didn't limit-up (e.g., a 7% gap-down from distribution). This is a signal the per-stock API misses.
2. **Competitors on the board**: Same-theme stocks may show heavy institutional buying while your position is quiet — this indicates theme rotation you'd miss with per-position queries.
3. **Sector capital flow**: Aggregate net buying across all board stocks in your themes reveals whether money is flowing into or out of your sectors.

### API signature

```python
ak.stock_lhb_detail_em(start_date="20260610", end_date="20260610")
```

Returns DataFrame with columns:
`['代码', '名称', '收盘价', '涨跌幅', '龙虎榜净买额', '龙虎榜买入额', '龙虎榜卖出额', '龙虎榜成交额', '市场总成交额', '换手率', '流通市值', '上榜原因', '上榜后1日', '上榜后2日', '上榜后5日', '上榜后10日']`

### Time guard

Board data publishes after 16:00-17:00. Only call the API when `current_time >= time(16, 0)`:

```python
if current_time >= time(16, 0):
    raw_board = _fetch_daily_dragon_tiger_board(date_today)
    if raw_board.get("available"):
        filtered = _filter_dragon_tiger_board(raw_board["board"], config)
```

### Net buy formatting (for raw number → readable string)

The total-board API returns `net_buy` as raw number strings (e.g., `"-24742823.28"`). Format them:

```python
def _format_net_buy_str(net_raw: str) -> str:
    \"\"\"\"-24742823.28\" → \"-2474万\", \"818000000\" → \"+8.18亿\"\"\"\"
    try:
        net_float = float(str(net_raw).strip().replace(",", ""))
        if abs(net_float) >= 100_000_000:
            return f"{'+' if net_float >= 0 else ''}{net_float / 100_000_000:.2f}亿"
        elif abs(net_float) >= 10_000:
            return f"{'+' if net_float >= 0 else ''}{net_float / 10_000:.0f}万"
        else:
            return f"{net_float:.0f}"
    except (ValueError, TypeError):
        return str(net_raw)


def _parse_net_buy_float(net_str: str) -> float:
    \"\"\"Parse \"+8.18亿\" → 818000000.0 for sorting.\"\"\"
```

### Deduplication: one code, best net_buy

A stock may appear multiple times on the board (e.g., "日涨幅偏离值达7%" + "连续三个交易日内涨幅偏离值累计达20%"). Deduplicate by code, keeping the entry with the largest |net_buy|:

```python
best_dt_per_code = {}
for entry in board:
    code = _pure_stock_code(entry.get("code", ""))
    if code not in watch_codes:  # only filter for watchlist/position stocks
        continue
    net_abs = abs(_parse_net_buy_float(entry.get("net_buy", "0")))
    if code not in best_dt_per_code or net_abs > best_dt_per_code[code]["_net_abs"]:
        best_dt_per_code[code] = {"entry": entry, "_net_abs": net_abs}
```

### Three-layer filter output

```python
_filter_dragon_tiger_board(board, config) → {
    "watch_dt_items": [      # Line: "雅克科技(002409) 净买+1.38亿"
        "雅克科技(002409) 净买+1.38亿",
        "昊华科技(600378) 净买-1.20亿",
    ],
    "dt_nettop5": [          # Dicts: top 5 by net_buy across ALL board stocks
        {"code": "002428", "name": "...", "net_buy": "+X亿"},
    ],
    "dt_sector_summary": {   # Aggregated by watchlist theme_id
        "ccL_resin_upstream": {
            "total_net_str": "+1.21亿",
            "stocks": ["002409"]
        }
    }
}
```

### Integration into agent context

In `_agent_context_data()`, the board data is injected as a top-level key triggered by time guard >= 16:00:

```python
"dragon_tiger_board": dt_board_data,
```

And in `format_agent_analysis_context()`, rendered as a text section:

```
=== 龙虎榜总榜 ===
你的池子上榜: 雅克科技(002409) 净买+1.38亿; 昊华科技(600378) 净买-1.20亿
全市场净买TOP: 002428(+X亿); 001696(+X亿); 688020(+X亿)
板块龙虎汇总: ccL_resin_upstream: +1.21亿 (2只); electronic_gas_wf6: -1.20亿 (1只)
上榜总数: 109只
```

### Design doc reference

See `docs/design/individual-stock-deep-analysis-design.md §7.4` for the full field spec and data structure design.

---

## Integration into Yesterday Summary (Phase 4.1)

### Trigger condition

Only fetch dragon/tiger data for stocks that limit-upped (`is_limit_up = True`). Non-limit-up stocks rarely appear on the board, so skip the API call entirely:

```python
if entry.get("is_limit_up"):
    dt_data = _fetch_dragon_tiger_data(code_pure, date_str)
    if dt_data.get("_error") and "未上榜" in dt_data["_error"]:
        pass  # not on board, leave null
    else:
        for key in ["dragon_tiger_net", "dt_seat_type",
                     "dt_top_buy_behavior", "dt_is_pure_hot_money",
                     "board_quality"]:
            if dt_data.get(key) is not None:
                entry[key] = dt_data[key]
```

### Output fields

| Field | Type | Example | Meaning |
|-------|------|---------|---------|
| `dragon_tiger_net` | str | "+8.18亿" | Total net buy amount (formatted) |
| `dt_seat_type` | str | "外资+机构+量化" | Participating seat categories |
| `dt_top_buy_behavior` | str | "做T" | Top buyer's expected next-day behavior |
| `dt_is_pure_hot_money` | bool | False | True if only 游资 seats present |
| `board_quality` | str | "strong" | Overall board strength assessment |

### Real example (002409 雅克科技, 2026-06-11)

```
龙虎榜净额:  +8.18亿          → 机构+外资大举买入
席位分布:   外资+机构+量化     → 深股通做T + 机构接盘 + 中金量化
买一行为:   做T              → 深股通同时买卖双向
非纯游资:   True             → 安全垫较高，不是游资接力
封板质量:   strong           → 净买入占优
```

### What this tells the LLM

Compare to pure hot-money plays:
- 002409 has INSTITUTIONS + FOREIGN CAPITAL involvement → less likely to crash next day
- Pure 游资 seats (all "游资" with no机构/外资) → high gap-down risk next day
- 做T behavior by top buyer → may sell into strength tomorrow
- 锁仓 behavior → likely to hold, reducing supply
