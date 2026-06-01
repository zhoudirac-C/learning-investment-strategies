# Index/ETF Buy Analysis Guide

## When to Use

When user asks about index (恒生科技、科创50、创业板指等) or ETF buy decisions using phrasing like:
- "恒生科技指数ETF适合买入吗"
- "最近可以买入恒生科技吗"
- "帮我看看恒生科技指数"
- Any index name + "买入/适合/看看"

## Key Difference from Individual Stock Analysis

| Dimension | Individual Stock | Index/ETF |
|-----------|-----------------|-----------|
| Core basis | Company fundamentals + industry logic | Macro framework + capital flow + time window |
| Claims source | Stock-specific claims in `knowledge/claims/` | Macro/market-cycle claims |
| Data source | Stock price + F10 + news | Index trend + constituent flow + macro data |
| Decision framework | Industry logic + technical breakout | Time window appropriateness + capital structure |

## Execution Flow

1. **Confirm scope**: Index/ETF vs individual stock. If user mentions "ETF" or index name explicitly, use this framework.
2. **Collect blogger claims**: Search `sources/raw/财经/` and `knowledge/claims/` for index-related judgments.
3. **Build timeline**: Arrange claims chronologically, marking risk windows, allocation windows, valuation recovery periods.
4. **Determine current position**: Current date vs timeline → identify which window we're in.
5. **ETF vs individual stock pros/cons**: ETF diversifies unlock risk, captures sector Beta, suits left-side batch buying; but cannot capture Alpha, includes weak constituents, has management fees.
6. **Output structure** (mandatory sections):
   - Core conclusion (one sentence: buy/no-buy, best window, recommended position)
   - Key blogger claims (chronological table)
   - Timeline visualization
   - Operation strategy (scenario-based table)
   - ETF selection advice (if applicable, with specific codes)
   - Risks and uncertainties
   - Key observation indicators

## Core Principles

- **Time window priority**: Blogger's index judgments depend heavily on time windows (unlock peaks, Fed meetings, earnings season). Even if valuation is low, heavy positions are not recommended during risk windows.
- **Distinguish A-share vs HK ecosystems**: HK is 80% institutional, suitable for left-side; A-shares suitable for right-side. ETFs fit better in HK for batch left-side buying.
- **Not just valuation**: Blogger explicitly says "HK never rises because it's cheap" — must look at earnings expectations and capital structure.
- **ETF as allocation tool**: Blogger accepts ETFs as defensive tools when risk appetite declines and as transitional core allocation, but not unconditional heavy positions.
- **Specific ETF codes required**: When user asks about ETFs, must provide specific on-exchange ETF codes (e.g., 513130, 513180) and off-exchange fund codes (e.g., 012348), with liquidity comparison.

## Common Pitfalls

1. Confusing individual stock and index analysis
2. Ignoring time windows — recommending buy just because valuation is low
3. Giving unconditional buy/sell instructions without conditions
4. Not distinguishing ETF vs individual stock advantages
5. Omitting specific ETF codes when user asks about ETFs

## Data Sources

- Index prices: Yahoo Finance (^HSTECH), Tencent Finance API
- Capital flow: Southbound daily net inflow (East Money, Wind)
- Unlock data: HKEX disclosures, broker research
- Macro data: Fed meetings, China PMI, RMB exchange rate
- Blogger claims: `sources/raw/财经/`, `knowledge/claims/`
