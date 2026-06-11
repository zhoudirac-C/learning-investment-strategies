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
   - `framework/reasoning-patterns.yaml` — 推理模式库（按 UP 的推理步骤分析）
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

When running from Hermes cron, always set the workdir to this repository root.
For local and cloud installs, prefer setting `HERMES_REPO_ROOT` to that path and
using it as the cron workdir.

## Git Discipline

- **Never use `git add -f` / `--force`** to bypass `.gitignore`. Files in
  `.gitignore` are excluded for a reason — `positions.yaml` contains private
  holding data, `storage/` and `.qdrant_data*` are auto-generated binaries.
- Use `git add -A` or `git add <file>` for staged changes.
- Before committing, verify with `git status --short` that no gitignored files
  are staged.

## Cron Script Architecture

Cron jobs reference scripts under `~/.hermes/scripts/` (the Hermes system scripts
directory). These are thin wrappers that delegate to the project's scripts:

```
~/.hermes/scripts/qing_stock_monitor_agent.py  →  project/scripts/hermes_stock_monitor_agent.py
~/.hermes/scripts/qing_stock_monitor_daily_review.py → project/scripts/hermes_stock_monitor_daily_review.py
~/.hermes/scripts/qing_stock_monitor_poll.py   →  project/scripts/qing_stock_monitor_poll.py
```

**Rule**: The `qing_` prefix files in `~/.hermes/scripts/` are STABLE entrypoints.
Never rename them. The `hermes_` files in the project can evolve freely. When
updating scripts, only modify the `hermes_` project versions — the wrappers
auto-delegate.

## Knowledge Maintenance

After adding new claims or updating existing ones (via raw document extraction),
run the full pipeline to sync Neo4j and Qdrant:

```
discover → Neo4j migrate → Qdrant rebuild → restart Agent
```

Full workflow documented in
[`docs/neo4j-relation-pipeline.md`](docs/neo4j-relation-pipeline.md).
