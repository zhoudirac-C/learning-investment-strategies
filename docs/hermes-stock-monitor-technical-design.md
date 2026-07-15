# Hermes Stock Monitor Technical Design

> Date: 2026-06-11 (updated from 2026-05-22)
> Scope: A-share intraday monitoring, rule-triggered Hermes analysis, and Weixin alerts.
> Principle: The system only sends alerts. It never places orders.
> Recent additions: P3 K-line entry zone, real-time quote injection (Fix B), hallucination detection (Fix A), K-line cache, buy signal detection, poll field lineage.

## Goal

Build a stock monitor that checks the user's holdings and watchlist during A-share trading hours, fetches live market data, applies configurable rules, and asks Hermes to analyze only when a meaningful trigger appears.

The main design goal is to avoid running a full LLM analysis every 10 minutes. Python should do the stable monitoring work; Hermes should explain important triggers and send alerts.

## Architecture

```text
Project configuration
  ├─ config/stock_monitor/positions.yaml
  ├─ config/stock_monitor/watchlist.yaml
  └─ config/stock_monitor/strategy_pack.yaml

Python monitor
  ├─ Load positions, watchlist, and strategy rules
  ├─ Fetch live index and stock quotes
  ├─ Evaluate index, sector, and holding rules
  ├─ Deduplicate and rate-limit alerts
  └─ Output context only when Hermes should analyze

Hermes
  ├─ Cron schedules monitor runs
  ├─ Receives script output as analysis context
  ├─ Uses AGENTS.md and qing-stock-analysis framework
  └─ Sends Weixin alerts
```

Current project entry points:

- `AGENTS.md`
- `config/stock_monitor/README.md`
- `config/stock_monitor/positions.example.yaml`
- `config/stock_monitor/watchlist.yaml`
- `config/stock_monitor/strategy_pack.yaml`
- `scripts/stock_monitor.py`
- `scripts/hermes_stock_monitor.py`
- `scripts/hermes_stock_monitor_analysis.py`
- `src/qing_investment/stock_monitor.py`

## Configuration Files

### positions.yaml

`config/stock_monitor/positions.yaml` is the private holding file. It is ignored by Git.

It records actual positions, costs, risk lines, and the intended handling style.

Example:

```yaml
accounts:
  - name: "账号1"
    positions:
      - code: "000021.SZ"
        name: "深科技"
        shares: 8000
        cost: 37.641
        role: "core_holding"
        strategy: "hold_or_t_reduce_concentration"
        reduce_zone: "36.9-37.5"
        risk_line: 35.90
        max_position_ratio: 0.45
        notes: "组合过度集中，反弹优先降集中度；不在低位恐慌卖。"
```

### watchlist.yaml

`config/stock_monitor/watchlist.yaml` is the public observation universe.

It records themes, source documents, core stocks, linked confirmation stocks, and stock-specific setups.

Example:

```yaml
themes:
  - id: "pcb_ccl"
    name: "PCB/CCL/电子玻纤布"
    source_docs:
      - "docs/标的深度研究/主板-方向二：国产算力产业链个股分析报告-20260518.html"
    stocks:
      - code: "002636.SZ"
        name: "金安国纪"
        role: "strong_repair_holding"
        segment: "覆铜板/电子玻纤布"
        confirm_with: ["生益科技", "南亚新材", "沪电股份", "胜宏科技"]
        buy_setup:
          - "不追高，仅在板块扩散且缩量回踩承接时观察"
        sell_setup:
          - "冲到48-50区间优先减亏T或减一部分"
          - "跌破44.5-43且资金转弱"
```

### strategy_pack.yaml

`config/stock_monitor/strategy_pack.yaml` contains reusable monitoring rules extracted from recent reviews and the project methodology.

It should contain:

- market stage
- index levels
- intraday schedule rules
- position handling rules
- notification policy
- sector groups and sector rotation rules

Index levels are not hardcoded in Python. They should live in this file and be updated from new review documents.

Example:

```yaml
index_rules:
  - index: "上证指数"
    watch_level: 4100
    valid_close_level: 4080
    weak_close_level: 4070
    trend_defense: 4027
```

The script executes these rules:

- below `weak_close_level`: weak repair alert
- below `trend_defense`: trend defense failure alert
- above `watch_level`: repair watch level recovered
- close above `valid_close_level`: repair is valid

## Sector Strength

Sector changes should not be guessed by the model. The monitor approximates sector strength through configured stock groups.

Recommended groups:

- Holdings-related offensive groups:
  - storage / 长鑫存储链
  - domestic compute / 国产算力
  - advanced packaging / 封测与先进封装
  - semiconductor materials / 半导体材料
  - PCB/CCL / PCB、覆铜板、电子布
- Current mainline groups:
  - semiconductor
  - AI hardware
  - CPO / optical communication
  - AI power, liquid cooling, data center energy
  - robotics
- Defensive comparison groups:
  - banks
  - liquor
  - pork
  - oil and gas
  - gold / nonferrous metals

Proposed config shape:

```yaml
sector_groups:
  - id: "storage"
    name: "存储链"
    type: "offensive"
    core_stocks: ["000021.SZ", "688525.SH", "001309.SZ", "300475.SZ"]

  - id: "pcb_ccl"
    name: "PCB/CCL"
    type: "offensive"
    core_stocks: ["002636.SZ", "600183.SH", "688519.SH", "002463.SZ", "300476.SZ"]

  - id: "defense_bank"
    name: "银行"
    type: "defensive"
    core_stocks: ["600036.SH", "601398.SH", "601288.SH"]
```

The monitor should compute:

- average percent change
- red-stock ratio
- volume or turnover change when available
- strength relative to indexes
- offensive-versus-defensive strength gap
- consecutive checks in the same direction

Example interpretation rules:

```text
Offensive red ratio > 60%
and offensive average gain > 1%
and offensive groups outperform defensive groups
=> technology active repair

Defensive average gain - offensive average gain > 1.5%
and offensive red ratio < 40%
=> defensive switch / weak repair

New theme outperforms old mainline by > 1.5% for two checks
=> possible theme switch, ask Hermes to analyze
```

## Stock Positioning (Three-Layer Method)

When Hermes analyzes an individual stock, it should determine the stock's position within its sector. This is critical for:
- Judging whether a stock is a leader, follower, or laggard
- Assessing sector health through intra-sector rankings
- Making hold/reduce decisions based on relative strength

### Layer 1: UP Knowledge Base

Query Neo4j for claims about the stock that contain position keywords (龙头/中军/趋势/情绪载体/先锋/补涨).

- If UP has labeled the stock → use UP's judgment as primary, verify with real-time data
- If UP has not labeled the stock → proceed to Layer 2

### Layer 2: Real-Time Sector Ranking

Use `stock_sector_mapper.py` to fetch the stock's real-time ranking within its sector:

```python
from qing_investment.agent.tools.stock_sector_mapper import get_stock_positioning

result = get_stock_positioning("002892")
# Returns: rank within sector, changepercent, mktcap, turnoverratio, position_tag
```

**Data sources** (cascading fallback):
1. Local cache: `config/stock_monitor/stock_sector_mapping.json` (O(1) lookup)
2. Sina `getHQNodeData`: real-time constituent ranking (1.5s interval between requests)
3. Sina `newFLJK`: sector list for reverse lookup

**Position tags**:

| Tag | Criteria | Action implication |
|-----|----------|-------------------|
| 日内龙头 | Top 3 in sector + gain > 5% | Strong conviction, leader status |
| 前排强势 | Top 5 in sector + gain > 3% | Healthy, front-runner |
| 中军/板块稳定器 | Mktcap > 50B + top 30% + gain > 0% | Institutional anchor, lower volatility |
| 趋势/趋势容量票 | Mktcap > 30B + gain > 0% + turnover < 8% | Trend play, suitable for holding |
| 跟风 | Bottom 50% + gain > 0% | Weak, avoid standalone entry |
| 弱势 | Gain <= 0% | Underperforming, trigger risk check |

### Layer 3: Synthesis

Combine Layer 1 and Layer 2:
- UP label present → prioritize UP's qualitative judgment, use real-time data for verification
- UP label absent → rely entirely on quantitative tags, but mark as "inferred, not UP-verified"
- Conflict between UP label and real-time data → flag the conflict, explain divergence

**Cache management**:
- Full rebuild: `scripts/build_sector_mapping.py` (~6-10 min for 259 sectors)
- Recommended cron: daily before market open (08:30)
- TTL: 24 hours

## Trigger Rules

Python should filter triggers first. Hermes should run only when there is something meaningful to explain.

Holding triggers:

- enters configured reduce zone
- breaks configured risk line and does not recover
- nears cost zone while sector does not confirm
- single-stock position ratio exceeds configured max ratio
- strong-repair stock enters reduce-loss zone

Index triggers:

- falls below weak repair line
- falls below trend defense line
- recovers repair watch level
- market state changes from weak repair to active repair or the reverse

Sector triggers:

- offensive groups confirm active repair
- defensive groups strongly outperform offensive groups
- original mainline weakens while a new theme leads for multiple checks
- a holding's sector becomes materially weaker than the market

Deduplication policy:

- same stock and same rule: alert at most once every 30 minutes
- sector switch: require at least two consecutive checks
- ordinary red/green movement: no alert
- non-trading time: silent, except explicit test mode

## Hermes Scheduling

**Schedule alignment** (2026-06-10): `14:55` → `14:52` tail-end order job, aligned with broker back-office cut-off. All schedules synced across `strategy_pack.yaml`, cron jobs, and prompt files.

The formal job should run in no-agent mode:

```bash
hermes cron create "*/10 * * * *" \
  --name "A股持仓与观察池监控" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor.py \
  --no-agent \
  --deliver weixin:o9cq805sx4bnLAAH-PXw04SOzBSY@im.wechat
```

This job should be quiet by default:

- no script output means no alert
- script output means Hermes or Hermes send should deliver an alert

For one-off live analysis tests:

```bash
hermes cron create "*/10 * * * *" \
  "基于脚本输出的实时行情、持仓、观察池和策略包，按AGENTS.md与qing-stock-analysis框架做一次简短分析。必须报告：行情请求耗时、整体判断、持仓分层、下一交易时段微信提醒触发条件、证伪条件。不要给无条件买卖指令。" \
  --name "A股监控分析一次性测试" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor_analysis.py \
  --deliver weixin:o9cq805sx4bnLAAH-PXw04SOzBSY@im.wechat \
  --repeat 1
```

## Cost Control

A full Hermes analysis test consumed about 0.07% of the user's plan quota.

If Hermes runs every 10 minutes:

```text
24 runs/day * 0.07% = 1.68% per trading day
20-22 trading days/month = about 34%-37% per month
```

The system should avoid this.

Recommended target:

```text
Python monitoring every 10 minutes
Hermes analysis only on triggers
Expected Hermes runs: 1-4 per active day
Estimated quota usage: about 1.4%-6% per month
```

## Data Flow

1. Hermes cron starts `qing_stock_monitor.py`.
2. Wrapper calls the project command under the repository root.
3. Python loads `positions.yaml`, `watchlist.yaml`, and `strategy_pack.yaml`.
4. Python fetches live quotes from Eastmoney.
5. Python evaluates configured index, sector, and holding rules.
6. If nothing triggers, it prints nothing.
7. If a rule triggers, it builds a structured JSON context with **real-time quote injection** for both positions and watchlist (`latest`/`pct_change` — Fix B).
8. `hermes_stock_monitor_agent.py` wraps the call: POSTs to Qing-Agent, runs **hallucination detection** (Fix A). If year 2025 detected → discard, fallback to local LLM.
9. Hermes analyzes the context with `AGENTS.md` and `qing-stock-analysis`.
10. Hermes delivers the final alert to Weixin.
11. The run output is archived under `~/.hermes/cron/output/`.

## Current Live Test Baseline

The one-off live test on 2026-05-22 used:

- source: Eastmoney `push2`
- quote count: 11
- quote request time: about 269 ms
- end-to-end Hermes analysis time: about 57 seconds

The analysis correctly produced:

- overall market judgment
- holding tiers
- next trading-session observation signals
- Weixin alert triggers
- invalidation conditions

## Implementation Plan

### Phase 1: General Rule Engine

Implement reusable rule types:

- `price_zone`
- `breakdown`
- `breakout`
- `position_concentration`
- `cost_near`
- `relative_strength`
- `relative_weakness`
- `sector_confirm`

Current implementation status:

- implemented: `price_zone`, `breakdown`/risk-line observation, configured index
  weak-repair/trend-defense observation, and stateless sector offensive-versus-
  defensive spread checks
- implemented: quote parsing disambiguates duplicate six-digit codes such as
  `1.000001` 上证指数 and `0.000001` 平安银行
- implemented: JSON state storage records the last quote snapshot and suppresses
  the same alert within a configurable de-duplication window
- implemented: sector signal counts and latest market-state summaries
- implemented: curl fallback for Eastmoney quotes when Python `urllib` is
  disconnected by the remote endpoint
- implemented: Hermes-agent escalation context for fixed key times and new rule
  alerts

### Phase 2: Sector Strength

Add `sector_groups` and `sector_rotation_rules` to `strategy_pack.yaml`.

Compute:

- average gain
- red ratio
- amount ratio when available
- offensive-versus-defensive spread
- consecutive signal count

### Phase 3: State Storage

Store monitor state in JSON or SQLite:

- last quote snapshot: implemented in `config/stock_monitor/state.json`
- last alert time per stock/rule: implemented through alert fingerprints
- consecutive sector strength count: implemented as `sector_signal_counts`
- last market state: implemented as `last_market_state`

### Phase 4: Triggered Hermes Analysis

When Python detects a trigger, print a compact context:

- trigger id
- affected stock/theme
- quote snapshot
- holding context
- relevant strategy rule
- what Hermes should answer

Current implementation status:

- implemented: `--agent-context-on-trigger` emits a Hermes-ready compact context
  when a configured key time is reached or a new rule alert appears
- implemented: seven fixed model-analysis times are configured in
  `agent_analysis_schedule`: `09:26`, `09:45`, `10:30`, `11:20`, `13:30`,
  `14:50`, and `15:05`
- implemented: fixed time prompts are de-duplicated once per trading day through
  `agent_analysis_history`
- implemented: `scripts/hermes_stock_monitor_agent.py` wraps the project command
  for Hermes agent cron jobs
- implemented: seven Hermes cron jobs were created on the local Hermes instance

Hermes then generates the Weixin-ready message.

### Phase 5: Daily Review

After market close, generate a monitoring review:

- triggered alerts
- suppressed alerts
- missed conditions
- false positives
- suggested YAML rule updates

Current implementation status:

- implemented: every tick records an `alert_decision_log` entry for emitted and
  de-duplicated suppressed alerts
- implemented: `--daily-review-context` emits a Hermes-ready end-of-day review
  context from `state.json`
- implemented: review context includes emitted alerts, suppressed alerts, agent
  runs, latest market state, sector signal counts, and data-source errors
- implemented: `scripts/hermes_stock_monitor_daily_review.py` wraps the project
  command for a 15:20 Hermes review job
- not yet automated: writing accepted YAML changes back into configuration
  files; the review proposes changes for manual confirmation first

## Recent Architecture Additions (2026-06-11)

### Real-Time Quote Injection (Fix B)

**What changed**: `stock_monitor._agent_context_data()` now injects `latest` and `pct_change` fields for both **positions** (existing) and **watchlist** (new Fix B) entries in the JSON context sent to Qing-Agent.

```python
# Position enrichment (existing)
"latest": quote["latest"],
"pct_change": quote["pct_change"],

# Watchlist enrichment (Fix B, line 1437-1440)
"latest": _to_float((_quote_for_stock(quotes_by_code, row.get("code", "")) or {}).get("latest")),
"pct_change": _to_float((_quote_for_stock(quotes_by_code, row.get("code", "")) or {}).get("pct_change")),
```

**Design**: Data comes from the real-time Eastmoney quote API at JSON construction time. Never written to `watchlist.yaml`. In-memory only.

**Prompt-level reinforcement (Fix C)**: `format_agent_analysis_context()` and `format_live_analysis_context()` both include:

```
【⚠️ 数据优先级】实时行情快照优先于下方 config 配置文件中的参考价。
```

### Hallucination Detection Wrapper (Fix A)

`hermes_stock_monitor_agent.py` now wraps the Qing-Agent call:

- 只调用一次 `/analyze/trigger`，将 `WATCHLIST_SHARD_SIZE` / `WATCHLIST_CORE_ONLY` 通过 `TriggerRequest.shard_size` / `TriggerRequest.core_only` 传入 Agent；具体的 watchlist 分片与并行扫描由 Qing-Agent LangGraph 内部完成。
- If `final_output` contains `"2025"` (current year is 2026) → mark **HALLUCINATION**
- Discard hallucinated output → fallback to local LLM with real-time data injected
- Fallback output quality is lower (no reasoning pattern matching) but data is correct

See [`docs/hallucination-defense-layers.md`](hallucination-defense-layers.md).

### P3 K-Line Entry Zone (Observation Pool)

**File**: `src/qing_investment/stock_monitor.py` — K-line driven entry zone for observation pool entries.

**Workflow**:
1. Poll reads `strategy_pack.yaml` entry_points with `entry_zone.price_range` field
2. Live price enters zone → auto-trigger notification
3. Trigger message format: `"【机会触发】{name} {price}（{pct_change}%）进入介入区间 {zone}。赔率 {odds}，止损 {stop_loss}"`

Reference: `skills/qing-stock-monitor-update/references/p3-kline-entry-zone-workflow.md`

### Poll Field Lineage Fix

**Problem**: Poll script read watchlist using old field paths that didn't match the restructured `strategy_pack.yaml` format.

**Fix**: Unified field access across all entry points — poll, agent context builder, and config update all use the same path scheme:

```yaml
entry_points:
  - code: 000534.SZ
    entry_zone:
      price_range: "30.5-31.0"    # poll reads here
      source_kline: "2026-06-08"
```

Reference: `skills/qing-stock-monitor-update/references/poll-field-lineage.md`

### K-Line Cache Layer (SQLite)

**What**: Pre-fetches daily K-lines before market open (06:30) for watchlist + positions. Poll and Agent layers read local cache first, fill missing data on demand.

**Benefit**: Reduces API duplicate calls and latency. Fallback when API is unreachable.

### Buy Signal Detection System

**Design doc**: `docs/design/buy-signal-detection-system.md` (v1.2, 2026-06-11)

Implements Phase 0-4 detection rules based on UP methodology:
- Phase 0: Sector rotation detection
- Phase 1: Price zone entry patterns
- Phase 2: Volume confirmation
- Phase 3: K-line shape analysis
- Phase 4: Multi-factor synthesis

### Cron Schedule Alignment

`14:55` → `14:52` tail-end order job, aligned with actual broker back-office cut-off. Config synced across `strategy_pack.yaml`, cron job schedules, and prompt files.

## Updated Implementation Status

### Phase 4 (updated): Triggered Hermes Analysis + Hallucination Detection

| Feature | Status |
|---------|--------|
| Seven fixed model-analysis times (09:26/09:45/10:30/11:20/13:30/14:52/15:05) | ✅ |
| Dedup via agent_analysis_history | ✅ |
| `scripts/hermes_stock_monitor_agent.py` wrapper | ✅ |
| Seven Hermes cron jobs created | ✅ |
| **Hallucination detection (Fix A) in wrapper** | **✅ 2026-06-10** |
| **Real-time quote injection for watchlist + prompt priority (Fix B+C)** | **✅ 2026-06-10** |

### Phase 5 (new): P3 K-Line Entry Zone + Buy Signal + Poll Integrity

| Feature | Status |
|---------|--------|
| P3 K-line driven entry zone price_range field | ✅ |
| Poll field lineage unification | ✅ |
| K-line cache layer (SQLite pre-fetch) | ✅ |
| Buy signal detection system (Phase 0-4) | ✅ Design doc, partial code |
| Cron schedule 14:55→14:52 alignment | ✅ |

## Operating Model

After implementation:

- add a new stock by editing `watchlist.yaml`
- update real holdings in `positions.yaml`
- update market levels in `strategy_pack.yaml`
- update methodology through claims/wiki/strategy pack
- modify Python only when a new indicator or rule type is required

This keeps the system flexible without turning every new stock into a code change.
