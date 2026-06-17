# Sector Theme From Knowledge — Build Watchlist Theme from UP's Framework

## Trigger

User asks: "UP之前讲过XX方向吗？有哪些标的？帮我加到观察池。"

Or: "把UP讲过XX的标的都加进去。"

## Workflow (6 Steps)

### Step 1: Knowledge Search — Full Search Chain

Do NOT search just one source. Search all three:

| Priority | Source | Method |
|----------|--------|--------|
| 1 | Claims (Qdrant) | `mcp_qdrant_search_claims(query=<sector>)` — semantic search, returns claim_id/subject/statement |
| 2 | Claims (Neo4j) | `mcp_neo4j_search_claims_graph(keyword=<sector>)` — exact keyword match on stock codes & sector names |
| 3 | Knowledge wiki | `search_files(pattern=<sector>, path=knowledge/wiki)` — read the dedicated wiki page if one exists |
| 4 | Original sources | If claims have `source_path` pointing to `sources/original/` or `sources/raw/`, read the source doc for full context |

**Critical discipline**: Claims are summaries — the full context (layered stock list, priorities, quotes) is in the wiki and original sources. Read the wiki page for the sector first.

### Step 2: Extract Stock List With Layer Info

UP typically organizes stocks by position in the value chain. Extract into this structure:

```
核心层（确定性优先）:
  - Stock A — code, logic, UP quotes
确定性扩展层（接近主流供应链）:
  - Stock B — code, logic
弹性层（上游材料/2026突破窗口）:
  - Stock C — code, logic (higher risk/PE)
ABF/FC-BGA载板（先进封装底座交叉）:
  - Stock D — code, logic
期权层（中长期突破跟踪）:
  - Stock E — code, logic (longer horizon, more uncertainty)
情绪锚点（不可交易，观测方向强度）:
  - Stock F — code, just sentiment gauge
```

If UP didn't explicitly layer them, infer from:
- **Core**: highest confidence, mentioned repeatedly, capacity core with orders
- **Extended**: confirmed supply chain but less developed
- **Elastic**: upstream materials, early breakthrough window, high PE
- **Option**: long-term, needs verification (client auth, revenue)
- **Sentiment**: flagship stock that leads sector moves (may be 300/688)

### Step 3: Filter By Mainboard Access

**Hard constraint** — user can only trade:
- `sh6xxxxx` (上海主板)
- `sz0xxxxx` (深圳主板: 000xxx, 002xxx)

Exclude:
- `300xxx` (创业板) — ❌
- `688xxx` (科创板) — ❌

For excluded stocks that are critical for direction tracking (e.g., 胜宏科技 300476 as PCB 中军), add them as `情绪锚点` with `position_ratio: 0` — they're sector thermometers, not tradable.

### Step 4: Pull Current Prices and Set Entry Zones

```bash
curl -s "https://qt.gtimg.cn/q=sz{code}" | iconv -f GBK -t UTF-8
# Parse: parts[3]=latest, parts[4]=prev_close, parts[39]=PE
```

Entry zone rules for P3-观察 (wait-and-see phase when 全A中阳线 is precondition):

| PE Range | Entry Zone Method | Example |
|----------|------------------|---------|
| < 80x (reasonable) | 均线法, MA10 ±3% | 中材科技 PE=56 → MA10附近 |
| 80-150x (elevated) | 回撤法, 8-20% from close | 东材科技 PE=168 → 50-58 |
| > 150x (extreme) | `position_ratio: 0` pure observation | 宏和科技 PE=625 |
| Negative PE | `position_ratio: 0` pure observation | 诺德股份 PE=-97 |

When market stage is "调整尾部等确认信号" — ALL entry zones are PRE-BUILD. Set price ranges as targets to watch, not buy orders. Only active when 全A中阳线 fires.

### Step 5: Build Theme YAML Structure

```yaml
- id: pcb_ai_chain
  name: PCB AI硬件链（成品板→CCL→上游材料→ABF载板）
  up_positioning: UP定性为... (direct quote or close paraphrase)
  source_docs:
  - knowledge/wiki/市场分析/PCB与先进封装.md
  - knowledge/claims/claim-20260525-006.yaml
  market_checks:
  - Key milestone 1
  - Key milestone 2
  stocks:
  # === 情绪锚点 ===
  - code: 002938.SZ
    name: 鹏鼎控股
    role: pcb_sentiment_anchor
    segment: PCB人气先锋/情绪载体
    priority: P3-观察
    watch_reason: Just a sector thermometer.
    lifecycle:
      stage: watching
      entered_stage: '2026-06-11'
  # === 核心层 ===
  - code: 600183.SH
    name: 生益科技
    role: ccl_core_material
    segment: 高速CCL/覆铜板
    priority: P3-观察
    watch_reason: UP core pick, M9 CCL, Rubin CCL upgrade key.
    confirm_with:
    - 沪电股份
    entry_zone:
      description: High position, wait for pullback + 全A中阳线
      current_ref: '2026-06-11 close=153.50 PE=94.92'
      price_range: 130.0 ~ 145.0
      method: 均线法, MA10附近
      confirm_signal: Pullback to zone + 全A中阳线
      hard_stop: 跌破120
      position_ratio: 不超过0.5成
    lifecycle:
      stage: watching
      entered_stage: '2026-06-11'
```

**Important rules**:
- `position_ratio: 0` for pure observation stocks — no entry_zone fields needed beyond note
- `price_range: null` for P3 stocks that shouldn't be traded — this prevents poll from treating them as actionable (see trap 31 in SKILL.md)
- Every stock needs a `role` that indicates its layer in the chain
- `confirm_with` should point to sibling stocks in the same layer

### Step 6: Validate and Commit

```bash
# 1. YAML syntax check
python3 -c "import yaml; yaml.safe_load(open('config/stock_monitor/watchlist.yaml'))"

# 2. Watchlist field validation
python3 scripts/validate_watchlist.py

# 3. No-agent script doesn't crash
PYTHONPATH=src timeout 30 .venv/bin/python scripts/stock_monitor.py --ignore-trading-time

# 4. Commit (no git add -f!)
git add config/stock_monitor/watchlist.yaml
git commit -m "feat: add <sector> theme with full UP分层 (N stocks)"
```

## Pitfalls

### Pitfall 1: Stacking P3 stocks in an existing theme vs new theme

If the sector already has a partial theme in watchlist (e.g., 沪电股份 already in `core_mainline_recovery`), decide:

| Situation | Decision |
|-----------|----------|
| New sector with 3+ stocks | Create dedicated theme (e.g., `pcb_ai_chain`) |
| 1-2 additional stocks for an existing theme | Add to existing theme |
| Stock is in one theme but fits another | Keep in original, add as cross-ref in new theme's `confirm_with` |

Don't duplicate full stock entries across themes. Keep the primary entry in one place.

### Pitfall 2: Ignoring existing stocks in watchlist

Before adding new stocks, check if any are already in the watchlist. Search `watchlist.yaml` for the sector's key codes. If already present, add to the new theme's `confirm_with` list instead of duplicating.

### Pitfall 3: Setting entry_zone.price_range for pure observation stocks

If a stock has `position_ratio: 0` (pure observation), its `price_range` must be `null`. Even if the YAML comment says "不预设介入", the poll script parses the raw YAML and will treat a numeric range as actionable. This caused a real bug in 2026-06-11 (trap 31-子案例 in SKILL.md).

```yaml
# ❌ Wrong — poll will treat as actionable
entry_zone:
  price_range: 140.0 ~ 165.0  # but also says "不建仓" in description
  position_ratio: 0.2成

# ✅ Correct — poll will skip this stock
entry_zone:
  price_range: null
  note: PE极端偏高，锁定观察不预设建仓
position_ratio: 0
```

### Pitfall 4: Missing the market stage context

All sector-theme additions during a "调整尾部等确认信号" phase must:
- Default to P3-观察 (not P2/P1)
- Require 全A放量中阳线 as confirm_signal in every entry_zone
- Have wider entry zone ranges (deeper pullback)
- Position size capped at 0.5成 or less

Don't set aggressive entry zones or short hard_stops during downtrend phases.

### Pitfall 5: Not linking knowledge sources

Every sector theme must have `source_docs` pointing to:
- The wiki page(s) from which the stock list was extracted
- The claims that contain the stock's positioning

This allows future updates (e.g., new UP claims about the same sector) to trace back to the source.

## Validated Example — PCB AI Hardware Chain

See `watchlist.yaml` theme `pcb_ai_chain` (added 2026-06-11, commit `95ddd39`):

- 11 stocks across 5 layers
- All P3-观察 with 全A中阳线 precondition
- 2 stocks as pure observation (宏和科技 PE=625, 诺德股份 PE=-97)
- Source linked to `knowledge/wiki/市场分析/PCB与先进封装.md` + claims
- Mainboard filter applied (排除 胜宏科技/隆扬电子/铜冠铜箔)
- 鹏鼎控股 added as sentiment anchor (tradable but direction-only)
