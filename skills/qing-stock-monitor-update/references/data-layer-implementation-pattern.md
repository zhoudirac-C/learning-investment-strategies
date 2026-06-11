# Data Layer Implementation Pattern for stock_monitor.py

## When to Add a New Data Layer

You're adding a new structured data set (e.g., yesterday summary, auction snapshot, cost basis) that:
- Combines data from multiple sources (API, state.json, kline cache, config)
- Has a well-defined field taxonomy
- Needs to survive across cron sessions (persistence)
- Should gracefully degrade when data sources are unavailable

## Pattern (3 Functions + 1 Integration)

### 1. Builder Function (`_build_*()`)

Aggregates data from all available sources into a single dict.

```python
def _build_foo(config, quote_snapshot, state, ...) -> dict:
    """Aggregate from multiple sources."""
    result = {"date": "...", "items": {}}
    
    # Source A: quote_snapshot (real-time API data)
    for pos in position_rows(config):
        quote = _quote_for_stock(quotes, code)
        close = _to_float(quote.get("previous_close"))
        ...
        
        # Initialize with nulls for all fields
        entry = {**{k: None for k in ALL_FIELDS}}
        entry["close"] = close
        
        # Source B: kline cache (MA calculations)
        klines = get_klines(code, days=30)
        entry["vs_ma5"] = _compute_vs_ma(close, klines, 5)
        
        # Source C: config (entry zones, costs)
        entry["entry_zone_distance"] = _check_entry_zone(...)
        ...
    
    return result
```

**Key rule**: Initialize ALL fields with `None`. Only overwrite the ones you have data for. This makes the output schema predictable and consumers can always check `is not None`.

### 2. Saver Function (`_save_*()`)

Writes to a JSON file with date-keyed structure.

```python
def _save_foo(summary: dict, config_dir=None) -> bool:
    file_path = (config_dir or DEFAULT_CONFIG_DIR) / "foo.json"
    existing = json.loads(file_path.read_text()) if file_path.exists() else {}
    date_str = summary["date"]
    existing[date_str] = summary
    file_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    return True
```

**Key patterns**:
- Date-keyed: `{"2026-06-11": {...}, "2026-06-12": {...}}`
- Always read-before-write to preserve history
- Wrap in try/except with `logger.error()` — never crash the main flow

### 3. Loader Function (`_load_*()`)

Three-level fallback chain: file > state.json snapshot > None.

```python
def _load_foo(config_dir=None, date_str=None) -> dict | None:
    # Level 1: File hit
    if file_path.exists():
        data = json.loads(...)
        if date_str in data:
            return data[date_str]
    
    # Level 2: Fallback to state.json's quote snapshot
    state = json.loads(state_path.read_text())
    qs = state.get("last_quote_snapshot", {})
    if qs.get("quotes"):
        return {"date": date_str, "items": {...}, "source": "fallback"}
    
    # Level 3: None
    logger.warning("Data unavailable for %s", date_str)
    return None
```

**Key patterns**:
- Each fallback level logs its source
- Lower levels return FEWER fields (only what's available)
- Consumers must handle `None` return

### 4. Integration

Hook into the existing CLI handler that runs at the right time:

```python
if args.some_context:
    state = load_monitor_state(state_path)
    print(format_some_context(config, state))
    
    # Auto-build and persist
    summary = _build_foo(config, state.get("quote_snapshot"), state, ...)
    _save_foo(summary)
    return 0
```

## Field Taxonomy

Organize fields into categories with constants for documentation and validation:

```python
SUMMARY_FIELDS_BASIC = ["close", "open", "high", "low", "change_pct", "volume", "amount"]
SUMMARY_FIELDS_BOARD = ["is_limit_up", "consecutive_limit_ups", "weak_board", ...]
SUMMARY_FIELDS_TECH = ["turnover_rate", "amplitude", "volume_ratio", "vs_ma5", ...]
SUMMARY_FIELDS_DETAIL = ["intraday_pattern", "dragon_tiger_net", ...]
SUMMARY_FIELDS_COST = ["avg_cost", "unrealized_pct", "cost_protection_line"]
ALL_SUMMARY_FIELDS = SUMMARY_FIELDS_BASIC + SUMMARY_FIELDS_BOARD + ...
```

Benefits:
- Design doc field list stays visible in code
- Auto-initialize all fields to None with `{k: None for k in SUMMARY_FIELDS_*}`
- Easy to count field coverage per stock

## Data Source Discrepancies (discovered in Phase 1)

| Source | Data | Staleness | Notes |
|--------|------|-----------|-------|
| `quote_snapshot.previous_close` | Yesterday's close | Real-time (API) | One number per stock, always fresh |
| `state.json` quote fields | OHLC + vol + amt | Last cron tick | May be hours old if cron skipped |
| Kline cache (SQLite) | OHLC + MA computation | Varies by stock | Some stocks have 3 entries, some 30. `turnover` field always None. Closes don't match API `previous_close` |
| `daily_state.json` | Market stage/direction | Last closing review | Updated by 15:20 cron |
| `strategy_pack.yaml` | Entry zones, key levels | Manual | User-maintained |

**Critical insight**: Don't expect cross-source consistency. The kline cache's `close` for 002409 can be 119.8 while the API's `previous_close` is 122.55. They're different data pipelines. Always document which source each field comes from.

## What to Capture in a New Data Layer

For each data source, document:
1. **When it's updated** (15:20 closing review, 06:30 kline pre-fetch, 09:26 auction)
2. **What it contains** (field list + types)
3. **What it's missing** (turnover always None, board features need external data)
4. **Fallback behavior** (file > state.json > None)
5. **Who consumes it** (format_agent_analysis_context, format_agent_json_context, individual stock prompts)

## Integration Points in stock_monitor.py

| Hook | When | What to do |
|------|------|-----------|
| `--daily-review-context` CLI | 15:20 closing review | Build + save yesterday summary |
| `--agent-json-context` CLI | Every cron node | Load and inject into context |
| `format_agent_analysis_context()` | Text context generation | Load + inject as text section |
| `_agent_context_data()` | JSON context generation | Load + inject as `yesterday_summary` key |
| `format_agent_json_context()` | Agent HTTP API | Same as above |

## Real Example: Phase 1 Yesterday Summary

See `docs/design/individual-stock-deep-analysis-design.md §1.1` for the field spec and `src/qing_investment/stock_monitor.py` lines 1340-1590 for the implementation.

Key implementation decisions:
- `is_limit_up` derived from `change_pct >= 9.5` (mainboard threshold)
- `amplitude` from kline cache if available, else (high-low)/close
- `volume_ratio` = today_volume / avg of last 5 days' volumes (from kline cache)
- `entry_zone_distance` checks both strategy_pack.entry_points[] and watchlist
- `cost_protection_line` tiered: realized P&L >10% → cost +5%, >5% → cost +3%, else cost
- Fields requiring unavailable data sources (`board_open_count`, `dragon_tiger_net`, etc.) initialize to null

## Extended Pattern: Auction Snapshot with Cache Backfill (Phase 2)

### Data source constraints

Auction data at 09:25-09:26 is available from the existing quote API (东方财富push2):
- `f17` (open) = match price at 09:25
- `f3` (pct_change) = (match price - previous close) / previous close
- `f5` (volume) = accumulated volume at 09:26 = auction volume
- After 09:30, `f2` (latest) diverges from `f17` as trading begins

**Critical**: `f5` at market close is full-day volume, NOT auction volume. Always time-guard auction extraction.

### Time guard pattern

Only compute auction snapshot during the valid window (09:20-09:30). Outside that window, skip extraction entirely — don't use stale quote_data:

```python
current_time = value.astimezone(CN_TZ).time()
if time(9, 20) <= current_time <= time(9, 31):
    raw_auction = _auction_snapshot(config, quote_snapshot, ...)
    # process auction data
else:
    auction_snapshot_data = {}  # empty = no auction data available
```

### Volume ratio: don't wait, backfill from kline cache

The `auction_volume_ratio` (today's auction volume / 5-day average auction volume) normally needs 5 days of auction cache data. **Don't wait** — backfill from kline cache immediately:

```python
# Backfill logic in _compute_auction_volume_ratio():
if len(past_volumes) < 5:
    klines = get_klines(code, days=10)
    for k in reversed(klines[-8:]):
        k_date = str(k.get("date", ""))
        if already_cached: continue
        k_volume = k.get("volume")
        cache[code].append({
            "date": k_date,
            "volume": k_volume * 0.5,  # scaling factor for auction vs full-day
            "source": "kline_backfill",
        })
```

The ratio is immediately usable (e.g., ratio=0.26 means today's auction is ~1/4 of typical daily volume). As real auction data accumulates over 5 trading days, the backfilled data is naturally replaced.

**User-corrected lesson**: The first implementation planned to wait 5 days for the cache to accumulate. The user said "你补拉前五天的缓存不行吗？" — backfill immediately from the more available data source (kline cache). The ratio is directional, not absolute, so even approximate backfill is informative.

### Auction cache persistence

Store as a flat JSON file (`auction_volume_cache.json`) with date-keyed entries per stock:
```json
{
  "002409": [{"date": "2026-06-11", "volume": 576461, "price": 126.22, "source": "live"}],
  "000636": [{"date": "2026-06-10", "volume": 863093, "price": null, "source": "kline_backfill"}]
}
```

Keep last 10 entries per stock (cap at `AUCTION_CACHE_MAX_DAYS = 10`). Each time _auction_snapshot() runs at 09:26, it appends today's entry and trims old ones.

## Extended Pattern: Cost Injection into Live Context (Phase 3)

Cost data (avg_cost, unrealized_pct, cost_protection_line) must be injected into `enriched_positions` in `_agent_context_data()`, NOT just in the yesterday_summary. This makes cost available at EVERY time node, not just in the summary.

### Injection location

```python
# Inside _agent_context_data(), enriched_positions loop:
enriched = dict(p)
latest = _to_float(quote.get("latest"))
cost = _to_float(p.get("cost"))
if cost and latest:
    unrealized_pct = round((latest - cost) / cost * 100, 2)
    enriched["avg_cost"] = cost
    enriched["unrealized_pct"] = unrealized_pct
    # Protection line logic (same as summary for consistency)
    if unrealized_pct > 10:
        enriched["cost_protection_line"] = round(cost * 1.05, 2)
    elif unrealized_pct > 5:
        enriched["cost_protection_line"] = round(cost * 1.03, 2)
    elif unrealized_pct > 0:
        enriched["cost_protection_line"] = round(cost * 1.00, 2)
    else:
        enriched["cost_protection_line"] = round(
            cost * (1.0 if unrealized_pct >= -3 else 0.95), 2
        )
```

### Cost protection line tiers

| unrealized_pct | protection_line | rationale |
|---|---|---|
| > +10% | cost × 1.05 | Lock in some profit |
| +5% to +10% | cost × 1.03 | Light profit protection |
| 0 to +5% | cost × 1.00 | Don't lose principal |
| -3% to 0% | cost × 1.00 | Defend cost basis |
| < -3% | cost × 0.95 | Allow -5% max loss |

### Text context injection

In `format_agent_analysis_context()`, add a "持仓成本" section between auction snapshot and output instructions so the LLM sees cost data in both JSON and text formats.

## Extended Pattern: Sector Tier from Watchlist Themes (Phase 4.2)

For each position stock, compute its ranking within its watchlist theme group by pct_change:

### Implementation approach

```python
def _build_sector_tiers(config, enriched_positions, quotes_by_code) -> dict:
    # 1. Build code→[theme_id] map from watchlist
    code_to_themes = {}
    for theme in config.watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            c = _pure_stock_code(stock.get("code", ""))
            code_to_themes.setdefault(c, []).append(theme["id"])
    
    # 2. Collect all stocks' real-time pct_change
    all_pct = {}  # code → pct_change (from quotes + positions)
    
    # 3. For each position, find peers in same theme → sort by pct_change
    for pos in enriched_positions:
        themes = code_to_themes.get(code_pure, [])
        peers = collect_stocks_in_theme(themes)
        peer_pct = [(c, all_pct.get(c)) for c in peers if pct exists]
        peer_pct.sort(key=lambda x: x[1], reverse=True)
        
        tier = {"avg_change": avg, "peers_count": len(peer_pct)}
        tier["tier1_code"], tier["tier1_pct"] = peer_pct[0]
        tier["tier2_code"], tier["tier2_pct"] = peer_pct[1] if len > 1 else ...
        tier["tier3_code"], tier["tier3_pct"] = peer_pct[2] if len > 2 else ...
        tier["self_rank"] = position in sorted list
```

### Output shape (injected into each position dict)

```python
pos["sector_tier"] = {
    "self_rank": 3,
    "self_rank_label": "T3",
    "peers_count": 4,
    "avg_change": 7.9,
    "tier1_code": "600500", "tier1_pct": 10.08, "tier1_is_position": False,
    "tier2_code": "002971", "tier2_pct": 10.01, "tier2_is_position": False,
    "tier3_code": "002409", "tier3_pct": 10.0,  "tier3_is_position": True,
}
```

### Key insight: interpret with context

- T3 in a 4-stock theme where all 4 stocks are +10% = **板块强度极高**, not weakness
- T1 in a 1-stock theme = **数据不完整** (only this stock has a real-time quote)
- The peer count (`peers_count`) tells you how complete the picture is

### Injection point

Compute in `_agent_context_data()` after `sector_strengths` are built. Inject into each position's dict individually (not as a top-level key), so the LLM sees it inline with the position.

### Dependency: watchlist theme membership

This only works for stocks that appear in a watchlist theme that has at least 2-3 other stocks also in the real-time quote snapshot. Stocks in singleton themes or themes where most stocks aren't being fetched will show limited tier data.


## Extended Pattern: Dragon/Tiger Board Full-Market Cross-Check (Phase 4.1b)

### Pattern overview

Dragon/tiger board cross-check adds a **global market data layer** that enriches the closing review with:
- Which watchlist/position stocks appeared on the board (including non-limit-up ones)
- Top 5 net-buy stocks across the entire market
- Sector-level capital flow aggregation by watchlist theme

### Data source

```python
ak.stock_lhb_detail_em(start_date="20260610", end_date="20260610")
# Returns: 109 rows for a typical day, columns include
# 代码, 名称, 收盘价, 涨跌幅, 龙虎榜净买额, 换手率, 上榜原因
```

### Implementation layers

| Layer | Function | Output |
|-------|----------|--------|
| Fetch | `_fetch_daily_dragon_tiger_board(date_str)` | `{available, board: [{code, name, net_buy, ...}], fetched_at}` |
| Filter | `_filter_dragon_tiger_board(board, config)` | `{watch_dt_items, dt_nettop5, dt_sector_summary}` |
| Parse | `_parse_net_buy_float(str) → float` | Sortable net_buy value |
| Format | `_format_net_buy_str(str) → "+1.38亿"` | Readable net_buy string |

### Time guard pattern

Board data is published after 16:00. Guard the API call:

```python
current_time = value.astimezone(CN_TZ).time()
if current_time >= time(16, 0):
    raw_board = _fetch_daily_dragon_tiger_board(date_today)
    if raw_board.get("available"):
        dt_board_data = _filter_dragon_tiger_board(raw_board["board"], config)
        # Inject into context
        data["dragon_tiger_board"] = dt_board_data
```

### Deduplication: same stock, multiple board entries

A stock can appear multiple times (different triggering conditions). Deduplicate by code, keeping the entry with largest |net_buy| — the highest-absolute-value entry is most representative of capital flow.

### Integration points

| Point | Location | What happens |
|-------|----------|-------------|
| JSON context | `_agent_context_data()` return dict | `"dragon_tiger_board": {...}` top-level key |
| Text context | `format_agent_analysis_context()` | "=== 龙虎榜总榜 ===" section |
| CLI hook | `--daily-review-context` handler | Not directly called here (data is fetched lazily in context building) |

### What the LLM learns

```python
# Example for 2026-06-11:
dragon_tiger_board = {
    "watch_dt_items": ["雅克科技(002409) 净买+1.38亿", "昊华科技(600378) 净买-1.20亿"],
    "dt_nettop5": [{"code": "002428", "name": "...", "net_buy": "+X亿"}],
    "dt_sector_summary": {
        "ccL_resin_upstream": {"total_net_str": "+1.21亿", "stocks": ["002409"]}
    }
}
```

- **雅克科技 +1.38亿**: Continuation likely (institutional accumulation)
- **昊华科技 -1.20亿**: Watch for distribution, may need to re-evaluate position
- **ccL_resin_upstream +1.21亿**: The theme is attracting net capital, validates the direction
- **109 total board stocks**: Market activity level reference

### Design doc reference

See `docs/design/individual-stock-deep-analysis-design.md §7.4` for the complete field spec.


## Extended Pattern: LLM Output Tomorrow Scenarios Persistence (Phase 4.3)

### Challenge

The `tomorrow_scenarios` are generated by the LLM during the 15:20 closing review, but the summary file is saved BEFORE the LLM runs (by `--daily-review-context` CLI). The LLM's output with `tomorrow_scenarios` goes to the user, not back to stock_monitor.py.

### Solution: separate persistence function

```python
def _update_summary_tomorrow_scenarios(
    tomorrow_scenarios: dict,  # {"strong_repair": {...}, ...}
    config_dir=None,
    date_str=None,
) -> bool:
    \"\"\"Called by the cron layer AFTER LLM responds.\"\"\"
    file_path = _summary_file_path(config_dir)
    existing = json.loads(file_path.read_text())
    existing[date_str]["tomorrow_scenarios"] = tomorrow_scenarios
    file_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    return True
```

### Integration point (Hermes cron layer)

The cron job that calls `--daily-review-context` and gets the LLM response should:
1. Parse ````daily_state` block from LLM output → calls existing `save_daily_state()`
2. Parse `tomorrow_scenarios` JSON block → calls `_update_summary_tomorrow_scenarios()`

This is intentionally NOT inside stock_monitor.py's CLI flow — it's a cron-layer concern because the LLM output is received by the Hermes scheduler, not by the Python script.

### Tomorrow scenarios data shape

```json
{
  "tomorrow_scenarios": {
    "strong_repair": {
      "probability": "30%",
      "auction_signature": "全A高开>0.5%，竞价量放大",
      "action_if_match": "持仓不动，观察加仓机会"
    },
    "weak_consolidation": {
      "probability": "50%",
      "auction_signature": "全A平开±0.3%，竞价量正常",
      "action_if_match": "做T为主，不新增净仓"
    },
    "strong_divergence": {
      "probability": "20%",
      "auction_signature": "全A低开>0.5%，竞价量萎缩或放量下杀",
      "action_if_match": "直接降仓，跌破risk_line执行风控"
    }
  }
}
```

Probabilities must sum to 100%. Each scenario has:
- `probability` — the LLM's estimated likelihood
- `auction_signature` — the specific auction pattern that would indicate this scenario is playing out
- `action_if_match` — what to do if this scenario materializes

This is used by the 09:26 prompt to set expectations: "根据昨日收盘复盘的明日剧本，判断当前竞价数据更符合哪个情景？"


## Context Injection Strategy

When adding new data layers to the agent context, use this decision tree:

```
Is the data time-sensitive (only valid at a specific window)?
  YES → Add time guard in _agent_context_data()
  NO  → Always inject

Is the data available from an API call or cached?
  API → Call in _agent_context_data() (cache for current tick)
  Cache → Load with fallback chain in _agent_context_data()

Does the text formatter need it too?
  YES → Add section in format_agent_analysis_context()
  NO  → JSON-only (format_agent_json_context)

Is it per-stock or global?
  Per-stock → Add to enriched_positions[] or auction_snapshot{}
  Global → Add as top-level key
```
