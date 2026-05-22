# Hermes Stock Monitor Technical Design

> Date: 2026-05-22  
> Scope: A-share intraday monitoring, rule-triggered Hermes analysis, and Weixin alerts.  
> Principle: The system only sends alerts. It never places orders.

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

The formal job should run in no-agent mode:

```bash
hermes cron create "*/10 * * * *" \
  --name "A股持仓与观察池监控" \
  --workdir /Users/cong.zhou/Documents/quantitative/learning-investment-strategies \
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
  --workdir /Users/cong.zhou/Documents/quantitative/learning-investment-strategies \
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
7. If a rule triggers, it prints a compact analysis context.
8. Hermes analyzes the context with `AGENTS.md` and `qing-stock-analysis`.
9. Hermes delivers the final alert to Weixin.
10. The run output is archived under `~/.hermes/cron/output/`.

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
  `agent_analysis_schedule`: `09:26`, `09:45`, `10:30`, `11:25`, `13:30`,
  `14:55`, and `15:05`
- implemented: fixed time prompts are de-duplicated once per trading day through
  `agent_analysis_history`
- implemented: `scripts/hermes_stock_monitor_agent.py` wraps the project command
  for Hermes agent cron jobs
- not yet implemented: automatic creation/update of the seven Hermes cron jobs
  on the local Hermes instance

Hermes then generates the Weixin-ready message.

### Phase 5: Daily Review

After market close, generate a monitoring review:

- triggered alerts
- suppressed alerts
- missed conditions
- false positives
- suggested YAML rule updates

## Operating Model

After implementation:

- add a new stock by editing `watchlist.yaml`
- update real holdings in `positions.yaml`
- update market levels in `strategy_pack.yaml`
- update methodology through claims/wiki/strategy pack
- modify Python only when a new indicator or rule type is required

This keeps the system flexible without turning every new stock into a code change.
