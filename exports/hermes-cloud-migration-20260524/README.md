# Hermes Cloud Migration Export

> Exported from local Hermes on 2026-05-24.
> This package is sanitized: it does not include Hermes auth files, `.env`, Weixin channel ids, local cron output logs, monitor state, or private `positions.yaml`.

## What This Migrates

- A-share monitor cron schedules from local `~/.hermes/cron/jobs.json`.
- Hermes script names and prompts.
- Cloud install commands with placeholders for repo path and delivery target.
- Required private files checklist.

## Files

- `cron-jobs.sanitized.json` — portable cron job definition with sensitive/local fields removed.
- `install-cloud-crons.sh` — commands for cloud Hermes to install the scripts and create cron jobs.
- `positions.cloud.template.yaml` — template for the private holdings file the cloud instance must create.

## Required Repo State

Cloud Hermes should use this repository branch after the latest push:

```bash
git clone git@github-personal:zhoudirac-C/learning-investment-strategies.git
cd learning-investment-strategies
git checkout master
uv sync
```

Set the cloud repository path explicitly:

```bash
export HERMES_REPO_ROOT=/path/to/learning-investment-strategies
```

The wrapper scripts now read `HERMES_REPO_ROOT`, so the same scripts can run locally and in cloud.

## Private Config To Recreate On Cloud

Create `config/stock_monitor/positions.yaml` on the cloud host. This file is intentionally not committed and not exported with real holdings.

Use:

```bash
cp exports/hermes-cloud-migration-20260524/positions.cloud.template.yaml config/stock_monitor/positions.yaml
```

Then fill the real account holdings and costs.

Cloud Hermes also needs its own:

- Hermes login/auth.
- Weixin delivery channel.
- Any market-data network access required by `skills/qing-stock-analysis/vendor/glmv-stock-analyst`.

Do not copy these local files directly unless you intentionally want to migrate secrets:

- `~/.hermes/.env`
- `~/.hermes/auth.json`
- `~/.hermes/config.yaml`
- `~/.hermes/channel_directory.json`
- `config/stock_monitor/state.json`
- `~/.hermes/cron/output/`

## Install Crons

Before reinstalling, check for old duplicate jobs on cloud:

```bash
hermes cron list --all
```

The 10-minute monitor must be `no-agent` with an empty prompt. If a cloud job
named `A股持仓与观察池监控` reports Kimi/OpenAI HTTP 429, it is not the expected
job shape. Pause or remove that stale job first:

```bash
hermes cron pause <job_id>
hermes cron remove <job_id>
```

On cloud:

```bash
cd "$HERMES_REPO_ROOT"
export HERMES_DELIVER_TARGET="weixin:<cloud-weixin-channel-or-user>@im.wechat"
bash exports/hermes-cloud-migration-20260524/install-cloud-crons.sh
```

The install script creates these jobs:

| Name | Schedule | Script | Agent |
|------|----------|--------|-------|
| A股持仓与观察池监控 | `*/10 * * * *` | `qing_stock_monitor.py` | no-agent |
| A股大模型分析-集合竞价后 | `26 9 * * 1-5` | `qing_stock_monitor_agent.py` | agent |
| A股大模型分析-开盘确认 | `45 9 * * 1-5` | `qing_stock_monitor_agent.py` | agent |
| A股大模型分析-30分钟确认 | `30 10 * * 1-5` | `qing_stock_monitor_agent.py` | agent |
| A股大模型分析-上午收盘前 | `20 11 * * 1-5` | `qing_stock_monitor_agent.py` | agent |
| A股大模型分析-午后风险窗口 | `30 13 * * 1-5` | `qing_stock_monitor_agent.py` | agent |
| A股大模型分析-尾盘条件单 | `50 14 * * 1-5` | `qing_stock_monitor_agent.py` | agent |
| A股大模型分析-收盘复盘 | `5 15 * * 1-5` | `qing_stock_monitor_agent.py` | agent |
| A股监控收盘复盘 | `20 15 * * 1-5` | `qing_stock_monitor_daily_review.py` | agent |

Expected request budget after a clean install: the 10-minute monitor makes zero
model calls; the fixed-time agent jobs make at most 7 intraday model calls plus
1 close review on trading days, and only when their script prints context.

## Smoke Test

After filling `positions.yaml`, run:

```bash
uv run python scripts/stock_monitor.py --status
uv run python scripts/stock_monitor.py --smoke
uv run python scripts/stock_monitor.py --agent-context-on-trigger --ignore-trading-time
uv run python scripts/stock_monitor.py --daily-review-context --ignore-trading-time
```

Expected: no Python import errors; `--status` prints monitor config; context commands print Hermes-ready context.
