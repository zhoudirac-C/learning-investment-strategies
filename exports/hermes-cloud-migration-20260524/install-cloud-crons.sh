#!/usr/bin/env bash
set -euo pipefail

: "${HERMES_REPO_ROOT:?Set HERMES_REPO_ROOT to the cloud repo path}"
: "${HERMES_DELIVER_TARGET:?Set HERMES_DELIVER_TARGET, for example weixin:<id>@im.wechat}"

mkdir -p "$HOME/.hermes/scripts"

cp "$HERMES_REPO_ROOT/scripts/hermes_stock_monitor.py" "$HOME/.hermes/scripts/qing_stock_monitor.py"
cp "$HERMES_REPO_ROOT/scripts/hermes_stock_monitor_agent.py" "$HOME/.hermes/scripts/qing_stock_monitor_agent.py"
cp "$HERMES_REPO_ROOT/scripts/hermes_stock_monitor_analysis.py" "$HOME/.hermes/scripts/qing_stock_monitor_analysis.py"
cp "$HERMES_REPO_ROOT/scripts/hermes_stock_monitor_daily_review.py" "$HOME/.hermes/scripts/qing_stock_monitor_daily_review.py"

chmod +x "$HOME/.hermes/scripts/qing_stock_monitor.py"
chmod +x "$HOME/.hermes/scripts/qing_stock_monitor_agent.py"
chmod +x "$HOME/.hermes/scripts/qing_stock_monitor_analysis.py"
chmod +x "$HOME/.hermes/scripts/qing_stock_monitor_daily_review.py"

AGENT_PROMPT="根据脚本输出的上下文，按AGENTS.md和qing-stock-analysis框架生成微信提醒。不要给无条件买卖指令，必须写触发条件、证伪条件和下一次观察时间。"
DAILY_REVIEW_PROMPT="根据脚本输出的收盘复盘上下文，评估今天提醒质量、误报/漏报、去重是否合理，并给出需要调整的YAML配置建议。不要给无条件买卖指令。"

hermes cron create "*/10 * * * *" \
  --name "A股持仓与观察池监控" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor.py \
  --no-agent \
  --deliver "$HERMES_DELIVER_TARGET"

hermes cron create "26 9 * * 1-5" "$AGENT_PROMPT" \
  --name "A股大模型分析-集合竞价后" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor_agent.py \
  --deliver "$HERMES_DELIVER_TARGET"

hermes cron create "45 9 * * 1-5" "$AGENT_PROMPT" \
  --name "A股大模型分析-开盘确认" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor_agent.py \
  --deliver "$HERMES_DELIVER_TARGET"

hermes cron create "30 10 * * 1-5" "$AGENT_PROMPT" \
  --name "A股大模型分析-30分钟确认" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor_agent.py \
  --deliver "$HERMES_DELIVER_TARGET"

hermes cron create "25 11 * * 1-5" "$AGENT_PROMPT" \
  --name "A股大模型分析-上午收盘前" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor_agent.py \
  --deliver "$HERMES_DELIVER_TARGET"

hermes cron create "30 13 * * 1-5" "$AGENT_PROMPT" \
  --name "A股大模型分析-午后风险窗口" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor_agent.py \
  --deliver "$HERMES_DELIVER_TARGET"

hermes cron create "55 14 * * 1-5" "$AGENT_PROMPT" \
  --name "A股大模型分析-尾盘条件单" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor_agent.py \
  --deliver "$HERMES_DELIVER_TARGET"

hermes cron create "5 15 * * 1-5" "$AGENT_PROMPT" \
  --name "A股大模型分析-收盘复盘" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor_agent.py \
  --deliver "$HERMES_DELIVER_TARGET"

hermes cron create "20 15 * * 1-5" "$DAILY_REVIEW_PROMPT" \
  --name "A股监控收盘复盘" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor_daily_review.py \
  --deliver "$HERMES_DELIVER_TARGET"
