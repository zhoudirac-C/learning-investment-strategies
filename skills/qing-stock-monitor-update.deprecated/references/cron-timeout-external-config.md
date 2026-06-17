# Cron 超时外部化配置

## 背景

Agent cron job（如 `qing_stock_monitor_agent.py`）的完整链路实测约 173s（行情 15s + HTTP API 119s + 开销 39s）。但 cron 频繁超时静默失败。

## 根因：Hermes scheduler 默认 120s 脚本超时

源码位置：`/home/ubuntu/.hermes/hermes-agent/cron/scheduler.py` 第 813 行

```python
_DEFAULT_SCRIPT_TIMEOUT = 120  # seconds
```

Hermes cron scheduler 在**最外层**执行脚本时强制 120s 超时。脚本内部的 `QING_AGENT_TIMEOUT=180` 和 `CRON_WRAPPER_TIMEOUT=200` 完全无效——脚本在 120s 就被 scheduler kill，根本没机会跑完。

## 完整的 6 层超时层级（从内到外）

| 层级 | 超时值 | 配置位置 | 影响 |
|------|--------|---------|------|
| LLM 推理 | 30-60s | 模型自身 | 单次 LLM 调用 |
| gunicorn worker | 120s | `gunicorn --timeout` | HTTP 请求处理 |
| 脚本 HTTP `urlopen` | 180s | `QING_AGENT_TIMEOUT` 环境变量 | 单次 API 调用 |
| 脚本 wrapper | 200s | `CRON_WRAPPER_TIMEOUT` 环境变量 | 文档化建议，无实权 |
| **Hermes scheduler** | **120s (默认)** | **`scheduler.py:813`** | **← 最外层杀手** |

> **关键**：当前 scheduler 120s < 脚本 HTTP 180s，脚本还在重试就被 kill。

## 解决方案

### 方式 1：环境变量（推荐，优先级最高）

```bash
# 在 Hermes 启动前设置，或写入 ~/.bashrc
export HERMES_CRON_SCRIPT_TIMEOUT=300
```

### 方式 2：config.yaml（需要重启 Hermes）

```yaml
# ~/.hermes/config.yaml
cron:
  script_timeout_seconds: 300
```

### 方式 3：模块 monkeypatch（仅测试用）

```python
from hermes.cron import scheduler
scheduler._SCRIPT_TIMEOUT = 300
```

## 优先级解析（源码 `_get_script_timeout()` 确定机制）

`scheduler.py` 第 818-848 行的解析顺序：

1. 检查模块级 `_SCRIPT_TIMEOUT` 是否被 monkeypatch
2. 检查环境变量 `HERMES_CRON_SCRIPT_TIMEOUT`
3. 检查 `config.yaml` 的 `cron.script_timeout_seconds`
4. 回退到 `_DEFAULT_SCRIPT_TIMEOUT = 120`

## 脚本层环境变量（供参考）

`scripts/hermes_stock_monitor_agent.py`：

```python
# 脚本内部 HTTP 超时（调 Qing-Agent）
QING_AGENT_TIMEOUT = float(os.environ.get("QING_AGENT_TIMEOUT", "180"))

# wrapper 层超时（文档化建议）
CRON_WRAPPER_TIMEOUT = float(os.environ.get("CRON_WRAPPER_TIMEOUT", "200"))
```

## 推荐最终配置

确保超时层级严格递增：

```
LLM(60s) < gunicorn(120s) < 脚本 HTTP(180s) < Hermes scheduler(300s)
```

```bash
# ~/.bashrc 或 Hermes 启动环境
export HERMES_CRON_SCRIPT_TIMEOUT=300
export QING_AGENT_TIMEOUT=180
export QING_AGENT_MAX_RETRIES=3
export CRON_WRAPPER_TIMEOUT=200  # 文档化建议，无实权
```

## 诊断命令

```bash
# 检查 Hermes scheduler 当前超时
grep "_DEFAULT_SCRIPT_TIMEOUT" /home/ubuntu/.hermes/hermes-agent/cron/scheduler.py

# 检查环境变量
echo "HERMES_CRON_SCRIPT_TIMEOUT=$HERMES_CRON_SCRIPT_TIMEOUT"
echo "QING_AGENT_TIMEOUT=$QING_AGENT_TIMEOUT"

# 手动运行 cron job 测完整链路耗时
cd ~/learning-investment-strategies
time .venv/bin/python scripts/hermes_stock_monitor_agent.py

# 单独测 /analyze/trigger 耗时
time curl -s --max-time 200 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"测试","session_id":"test","analysis_type":"market"}'
```

## 注意事项

- `CRON_WRAPPER_TIMEOUT` 只是一个文档化建议——**对实际超时无约束力**
- 真正控制超时的是 Hermes scheduler 的 `_DEFAULT_SCRIPT_TIMEOUT`（120s）
- Hermes cron API 的 `cronjob` 工具不支持 `timeout` 字段设置
- 设置 `HERMES_CRON_SCRIPT_TIMEOUT` 后需要重启 Hermes cron scheduler 生效
