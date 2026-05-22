# Project Instructions For Hermes

This repository is a personal investment research and learning system. For any
stock analysis, trading monitor, market review, portfolio review, or intraday
alerting task, use the local project framework before giving conclusions.

## Required Workflow

1. Read `skills/qing-stock-analysis/SKILL.md`.
2. Follow these references when relevant:
   - `framework/stock-analysis-playbook.md`
   - `skills/qing-stock-analysis/references/data-source-strategy.md`
   - `skills/qing-stock-analysis/references/glmv-stock-analyst-workflow.md`
   - `skills/qing-stock-analysis/references/f10-financial-analysis.md`
   - `skills/qing-stock-analysis/references/qing-stock-framework.md`
   - `skills/qing-stock-analysis/references/report-contract.md`
3. Use local knowledge before generic market reasoning:
   - `knowledge/claims`
   - `knowledge/wiki`
   - `knowledge/cases`
   - `sources/raw/财经`
   - `docs/标的深度研究`
4. For real-time market data, follow
   `skills/qing-stock-analysis/references/data-source-strategy.md`.
5. Distinguish evidence, interpretation, and inference.
6. Do not provide unconditional buy/sell commands. Always include trigger
   conditions, invalidation conditions, and data timestamp.

## Stock Monitor Context

The stock monitor configuration lives in `config/stock_monitor/`.

- `watchlist.yaml`: stock universe, themes, roles, and linkage checks.
- `positions.yaml`: private current holdings and costs. This file is ignored by
  Git.
- `positions.example.yaml`: safe template for positions.
- `strategy_pack.yaml`: reusable monitoring rules extracted from the local
  methodology and recent reviews.

When running from Hermes cron, always set the workdir to this repository:

`/Users/cong.zhou/Documents/quantitative/learning-investment-strategies`
