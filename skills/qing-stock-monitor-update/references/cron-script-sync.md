# Cron 脚本双向同步规范

> Hermes cron 运行时从 `~/.hermes/scripts/` 读取脚本，但项目源码在 `~/learning-investment-strategies/scripts/`。修改时必须保持两边一致。

---

## 问题背景

Hermes cron 任务的 `Script` 字段只能指定 `~/.hermes/scripts/` 目录下的文件名（相对路径），不支持绝对路径。因此存在两个脚本位置：

- **运行时**：`~/.hermes/scripts/<script>.py` — cron 实际执行
- **项目源码**：`~/learning-investment-strategies/scripts/<script>.py` — git 管理、开发版本

## 同步策略演变

### 方案一：软链接（已废弃，2026-06-04 实测被 Hermes cron 拒绝）

Hermes cron 的脚本路径校验会**解析 symlink 的 canonical path**，若目标路径在 `~/.hermes/scripts/` 之外，则拒绝执行并报错：

```
Blocked: script path resolves outside the scripts directory (/home/ubuntu/.hermes/scripts): 'qing_stock_monitor_agent.py'
```

即使 `ls ~/.hermes/scripts/` 显示文件存在，只要它是 symlink 且指向项目 repo，就会被拒绝。

### 方案二：硬拷贝 + 同步脚本（当前推荐）

1. **项目目录为唯一源码**：`~/learning-investment-strategies/scripts/` 下的脚本是 git 管理的唯一源码。
2. **部署时复制到 `~/.hermes/scripts/`**：
   ```bash
   cp ~/learning-investment-strategies/scripts/hermes_stock_monitor_agent.py \
      ~/.hermes/scripts/qing_stock_monitor_agent.py
   cp ~/learning-investment-strategies/scripts/hermes_stock_monitor_daily_review.py \
      ~/.hermes/scripts/qing_stock_monitor_daily_review.py
   ```
3. **每次修改后重新复制**：修改项目版本后，必须重新执行上述 `cp` 命令，确保两边一致。
4. **自动化同步**：可在项目目录添加 `scripts/sync-to-hermes.sh`：
   ```bash
   #!/bin/bash
   for f in hermes_stock_monitor_agent.py hermes_stock_monitor_daily_review.py; do
       cp "$(dirname "$0")/$f" "$HOME/.hermes/scripts/${f/hermes_stock_monitor_/qing_stock_monitor_}"
   done
   echo "Synced at $(date)"
   ```

### 方案三：使用 `prompt` 字段替代 `script`（无需文件同步）

不依赖 `~/.hermes/scripts/` 中的文件，直接在 cron job 的 `prompt` 中写完整命令：

```json
{
  "action": "create",
  "name": "stock-monitor-agent",
  "schedule": "*/10 * * * 1-5",
  "prompt": "cd /home/ubuntu/learning-investment-strategies && HERMES_REPO_ROOT=/home/ubuntu/learning-investment-strategies python scripts/stock_monitor.py --agent-context-on-trigger",
  "workdir": "/home/ubuntu/learning-investment-strategies",
  "deliver": "weixin"
}
```

**优势**：无需文件同步，命令直接可见，不受脚本路径校验限制。  
**劣势**：命令较长，每次修改需更新 cron job 定义而非只改脚本。

## 方案对比

| 方案 | 优点 | 缺点 | 当前状态 |
|------|------|------|----------|
| 软链接 | 单点修改、无复制漂移 | **被 Hermes cron 拒绝** | 不可用 |
| 硬拷贝 | 兼容 Hermes cron | 需手动同步 | 可用 |
| `prompt` 字段 | 无需文件、直接命令 | 命令较长、无脚本复用 | 可用 |

## 废弃脚本处理

旧版本/重命名副本应移入 `~/.hermes/scripts/deprecated/`，不要直接删除（便于回滚和审计）：

```bash
mkdir -p ~/.hermes/scripts/deprecated
mv ~/.hermes/scripts/qing_stock_monitor.py deprecated/
mv ~/.hermes/scripts/hermes_stock_monitor.py deprecated/
mv ~/.hermes/scripts/qing_stock_monitor_analysis.py deprecated/
mv ~/.hermes/scripts/run_stock_monitor.sh deprecated/
```

## 验证清单

修改 cron 脚本后：
- [ ] 项目目录 `~/learning-investment-strategies/scripts/` 已更新
- [ ] `~/.hermes/scripts/` 下是**真实文件**（`ls -la` 不显示 `->`）或使用的是 `prompt` 字段
- [ ] 直接运行测试通过：`python3 ~/.hermes/scripts/qing_stock_monitor_agent.py --status`
- [ ] 废弃旧脚本已移入 `deprecated/`
- [ ] `hermes cron list` 确认 Script 字段指向正确的文件名（或 Prompt 字段包含完整命令）

## 常见陷阱

1. **只改一边**：改了项目版本但 `~/.hermes/scripts/` 还是旧副本 → cron 运行旧代码
2. **使用 `uv run` 超时**：cron 环境下 `uv run` 每次启动都要检查/创建虚拟环境，耗时可能超过 60s，导致 terminal 工具超时，任务失败。解决方案：脚本内部优先使用 `.venv/bin/python` 直接运行，`.venv` 不存在时 fallback 到 `uv run`。项目目录下所有 `hermes_stock_monitor_*.py` 已统一实现该逻辑。
3. **脚本名混淆**：
   - `qing_stock_monitor.py` — 旧 wrapper（已废弃）
   - `hermes_stock_monitor.py` — 旧 wrapper（已废弃）
   - `qing_stock_monitor_agent.py` — 当前使用的 agent wrapper（硬拷贝到 `~/.hermes/scripts/`）
   - `qing_stock_monitor_daily_review.py` — 当前使用的复盘 wrapper（硬拷贝到 `~/.hermes/scripts/`）
4. **软链接残留**：旧的 symlink 未被清理，cron 任务仍指向它 → 报错 "resolves outside the scripts directory"。修复：`rm ~/.hermes/scripts/*.py` 后重新 `cp`。
5. **workdir 设置错误**：cron job 的 `workdir` 必须指向项目 repo 根目录（`~/learning-investment-strategies/`），不能是 `~/.hermes/hermes-agent/`。错误的 `workdir` 会导致脚本找不到 `config/stock_monitor/` 下的配置文件。
