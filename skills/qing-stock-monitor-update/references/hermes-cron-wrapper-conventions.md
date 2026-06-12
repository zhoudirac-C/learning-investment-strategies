# Hermes Cron 包装器设计约定

> 对应 SKILL.md 陷阱 20/21/23。记录 Hermes cron wrapper 的设计模式和常见失效模式。

## 架构

```
~/.hermes/scripts/qing_*.py   ← 稳定入口（cron script 字段引用，永不改名）
    │ subprocess
    ▼
project/scripts/hermes_*.py   ← 实际逻辑（可演进，可重命名）
    │ subprocess -m
    ▼
python -m qing_investment.xxx ← 核心模块
```

## 包装器模板

所有 Hermes 包装器使用统一模板，不再硬编码文件路径：

```python
#!/usr/bin/env python3
"""Hermes cron entrypoint → delegates to project via python -m."""
import os, subprocess, sys
from pathlib import Path

ROOT = Path("/home/ubuntu/learning-investment-strategies")
VENV = ROOT / ".venv" / "bin" / "python"
PYTHON = str(VENV) if VENV.exists() else sys.executable

env = os.environ.copy()
env["PYTHONPATH"] = f"{ROOT}/scripts:{ROOT}/src"

sys.exit(subprocess.call(
    [PYTHON, "-m", "module_name"] + sys.argv[1:],
    cwd=ROOT, env=env,
))
```

## 关键规则

1. **cron script 字段只能引用 `~/.hermes/scripts/` 下的文件**，Hermes scheduler 不从 project 目录解析
2. **subprocess 调用永远用 `-m`**，不用文件路径（`python scripts/xxx.py` 会在文件重命名后静默失效）
3. **PYTHONPATH 必须同时包含 `scripts` 和 `src`**：`scripts/` 下的独立脚本需要前者；`qing_investment` 包需要后者
4. **venv Python 优先**（`ROOT/.venv/bin/python`），fallback 到 `sys.executable`

## 失效模式速查

| 症状 | 根因 | 修复 |
|------|------|------|
| 0 字节输出 + status=ok | script 字段文件名在 `~/.hermes/scripts/` 不存在 | 检查文件名，改回 `qing_*` 前缀 |
| 0 字节输出 + 昨日正常 | 包装器内部用 `python scripts/xxx.py`，文件改名后失效 | 改为 `python -m module_name` |
| 有内容但非 Qing-Agent 格式 | script 字段指向 project/scripts/ 下文件，Hermes 找不到→LLM fallback | 确认文件在 `~/.hermes/scripts/` 下 |
| ModuleNotFoundError | PYTHONPATH 缺了 src/ 或 scripts/ | 同时设置 `scripts:src` |

## no_agent 模式说明

当 cron job 设置为 `no_agent: true` 时，Hermes scheduler 直接执行 `script` 字段引用的脚本，**不走 LLM**。输出由 `deliver` 字段控制：
- `deliver: local`：仅保存到本地文件，不推送
- `deliver: weixin`：推送微信（仅用于有阈值触发的纯规则检查）

此模式下可用**简单 shell 包装器**替代 Python 包装器（因为不需要 subprocess 管理）：

```bash
#!/bin/bash
# ~/.hermes/scripts/update_index_klines_intraday.sh
cd ~/learning-investment-strategies || exit 1
exec ~/.hermes/hermes-agent/venv/bin/python3 scripts/update_index_klines_intraday.py "$@"
```

关键点：`exec` 确保脚本 PID 替换 shell PID，scheduler 能正确捕获退出码和 stdout。

## 涉及的全部包装器（2026-06-11 已修复）

| 包装器 | 模块调用 | 用途 |
|--------|---------|------|
| `qing_stock_monitor_agent.py` | `-m hermes_stock_monitor_agent` | Agent 分析 cron |
| `qing_stock_monitor_daily_review.py` | `-m hermes_stock_monitor_daily_review` | 收盘复盘 cron |
| `qing_stock_monitor_poll.py` | `-m qing_investment.stock_monitor` | 条件轮询 cron |
| `build_sector_mapping.py` | `-m build_sector_mapping` | 板块映射缓存 |
| `calc_hot_scores.py` | `-m calc_hot_scores` | 热度分计算 |
| `qing_pre_fetch_klines.py` | `-m pre_fetch_klines` | K线预拉取 |
| `update_index_klines_intraday.sh` | shell → `scripts/update_index_klines_intraday.py` | **指数K线盘中增量更新（no_agent）.sh 包装器** |
