# Agent Analysis Schedule 时间限制绕过

## 背景

`stock_monitor.py` 的 `find_agent_analysis_trigger()` 函数会检查当前时间是否匹配 `strategy_pack.yaml` 中的 `agent_analysis_schedule`。如果 cron job 的时间不在 schedule 中，函数返回 `None`，导致 Agent 分析静默跳过。

这造成了一个问题：cron schedule 和 agent_analysis_schedule 必须严格同步。修改 cron 时间时如果忘记同步 strategy_pack，就会出现"cron 触发但无输出"的静默失败。

## 解决方案（2026-06-10）

新增 `--agent-any-time` CLI 参数和 `find_any_agent_analysis_trigger()` 函数，绕过时间限制。

### 代码改动

#### 1. `stock_monitor.py`

- 新增 `find_any_agent_analysis_trigger()` 函数：
  - 仍然检查 event-driven triggers（alerts）
  - 对于 scheduled triggers：尝试匹配 schedule 中的行获取 metadata，匹配不到则创建 generic trigger
  - 不因为时间不在 schedule 中而返回 `None`

- 修改 `run_tick()`：新增 `agent_any_time: bool = False` 参数
  - 当 `agent_any_time=True` 时调用 `find_any_agent_analysis_trigger()`
  - 当 `agent_any_time=False` 时保持原有行为（向后兼容）

- 新增 CLI 参数 `--agent-any-time`

#### 2. `hermes_stock_monitor_agent.py`

- `fetch_json_context()` 和 `fetch_fallback_text_context()` 自动传递 `--agent-any-time`
- 这样 wrapper 脚本调用时无需额外参数即可绕过时间限制

### 使用方式

```bash
# 直接调用 stock_monitor.py（开发测试）
python3 scripts/stock_monitor.py --agent-json-context --agent-any-time

# wrapper 脚本自动使用（生产环境）
python3 scripts/hermes_stock_monitor_agent.py
```

### 向后兼容

- 不传递 `--agent-any-time` 时保持原有行为
- `DEFAULT_AGENT_ANALYSIS_SCHEDULE` 仍然作为 fallback
- `is_scheduled_agent_analysis_time()` 未被修改

## 相关文件

- `src/qing_investment/stock_monitor.py`
- `scripts/hermes_stock_monitor_agent.py`
