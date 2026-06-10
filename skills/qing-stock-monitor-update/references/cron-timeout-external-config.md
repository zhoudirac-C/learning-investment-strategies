# Cron 超时外部化配置

## 背景

Agent cron job 的默认超时是 120s，但 `QING_AGENT_TIMEOUT` 已调到 180s。这导致脚本还在重试时就被 cron kill，触发静默 fallback。

## 解决方案

将超时时间外部化为环境变量，避免硬编码。

### 脚本层

`scripts/hermes_stock_monitor_agent.py`：

```python
# 脚本内部 HTTP 超时（调 Qing-Agent）
QING_AGENT_TIMEOUT = float(os.environ.get("QING_AGENT_TIMEOUT", "180"))

# wrapper 层超时（供 cron 参考）
CRON_WRAPPER_TIMEOUT = float(os.environ.get("CRON_WRAPPER_TIMEOUT", "200"))
```

### Cron 层

Hermes cron API 的 `timeout` 字段需要通过重新创建 job 来设置。当前 workaround：

1. 在 cron job 的 prompt/script 中设置环境变量
2. 或者通过 `~/.bashrc` / cron 环境注入

### 推荐配置

```bash
# ~/.bashrc 或 cron 环境
export QING_AGENT_TIMEOUT=180
export QING_AGENT_MAX_RETRIES=3
export CRON_WRAPPER_TIMEOUT=200
```

### 超时层级关系

```
Qing-Agent 内部 LLM 调用: ~30-60s
Qing-Agent HTTP 端点处理: --timeout 120 (gunicorn)
脚本 HTTP 超时: QING_AGENT_TIMEOUT=180 (urllib)
Cron job 超时: CRON_WRAPPER_TIMEOUT=200 (Hermes cron)
```

每一层都必须比内层大，否则外层会 kill 内层。

## 诊断命令

```bash
# 检查当前 cron job 超时设置
cronjob action=list | grep -A5 "A股大模型分析"

# 检查环境变量
echo $QING_AGENT_TIMEOUT $CRON_WRAPPER_TIMEOUT

# 测试脚本超时行为
timeout 200 python3 scripts/hermes_stock_monitor_agent.py
```

## 注意事项

- Hermes cron API 的 `update` 操作不支持修改 `timeout` 字段
- 如需修改超时，可能需要删除并重新创建 job
- `CRON_WRAPPER_TIMEOUT` 目前只是文档化建议，实际 cron 超时由 Hermes 调度器控制
