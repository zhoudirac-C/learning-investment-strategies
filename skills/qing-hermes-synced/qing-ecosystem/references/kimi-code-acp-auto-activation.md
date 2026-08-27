# Kimi Code ACP 自动激活排查

## 问题场景

即使 `kimi-bridge.service` 已停止（`ActiveState=inactive`），且 Qing-Agent `.env` 中 `KIMI_CODE_ACP_FIRST=0`，`/home/ubuntu/.kimi-code/bin/kimi acp` 进程仍可能被外部触发并反复启停。

## 症状

1. **网络层**：Mihomo 代理日志大量 `api.kimi.com:443` TCP 连接
   ```bash
   journalctl --since 'today 09:46' --until 'today 09:55' | grep mihomo | grep 'api.kimi.com'
   ```
2. **进程层**：Kimi CLI 日志显示 10+ 次反复启停
   ```bash
   grep '2026-07-30' ~/.kimi-code/logs/kimi-code.log
   # 典型输出：
   # experimental flags enabled  flags=[]
   # acp: received signal, draining harness  signal=SIGTERM
   # 循环约10次
   ```
3. **磁盘层**：`~/.kimi-code/session_index.jsonl` 和 session 目录时间戳频繁更新

## 排查步骤

### Step 1：确认触发源不是 Bridge

```bash
systemctl status kimi-bridge.service
# 预期：Active: inactive (dead)
journalctl -u kimi-bridge.service --since 'today 09:00'
# 预期：No entries（今天未启动过）
```

### Step 2：确认触发源不是 Qing-Agent

```bash
grep KIMI_CODE_ACP_FIRST /home/ubuntu/learning-investment-strategies/.env
# 预期：KIMI_CODE_ACP_FIRST=0（禁用 ACP 优先）
grep 'kimi\|acp' /home/ubuntu/learning-investment-strategies/agent.log | tail -10
# 预期：无 kimi-acp 相关的 agent 调用
```

### Step 3：识别可能的触发源

两个已知的可能来源，按概率排序：

| 可能性 | 来源 | 触发机制 |
|:--:|------|---------|
| ⭐⭐ | **Hermes `kimicode` provider** | Hermes 在模型池初始化时探测 provider 健康状态，触发 `kimi acp` session 维护 |
| ⭐ | **Kimi Code CLI session 维护** | 工作区下存在 3000+ 历史 sessions，CLI 自身可能在后台做 session 回收/清理 |

### Step 4：根除方案（如需）

彻底禁用 Kimi Code CLI 唤醒：

```bash
# 方案A：从 Hermes config 移除 kimicode provider
# 编辑 ~/.hermes/config.yaml，删除 providers.kimicode 块

# 方案B：移走 CLI 二进制（可逆）
mv ~/.kimi-code/bin/kimi ~/.kimi-code/bin/kimi.disabled

# 方案C：删除旧 sessions 减少维护开销（不可逆）
rm -rf ~/.kimi-code/sessions/wd_learning-investment-strategies_4366e2e4f8b8/
```

## 已知案例

- **2026-07-30 09:46-09:54**：在所有保护措施（bridge 停、ACP_FIRST=0）已生效的情况下，CLI 仍被激活约 8 分钟，产生 31 次 API 连接。最终自行退出。

## 不构成"唤醒"的信号

以下情况**不**算自动激活，属于正常交互：
- 手动运行 `kimi -p "prompt"` 或 `kimi -c`
- 脚本开启的 kimi acp（如 bridge 启动时）
- Qing-Agent 在 `KIMI_CODE_ACP_FIRST=1` 时主动调用

## 相关配置路径

| 文件 | 用途 |
|------|------|
| `~/.kimi-code/config.toml` | CLI 模型/Provider 配置 |
| `~/.kimi-code/logs/kimi-code.log` | CLI 运行时日志 |
| `~/.kimi-code/session_index.jsonl` | 所有 session 索引 |
| `~/.kimi-code/workspaces.json` | 工作区注册表 |
| `~/.kimi-code/updates/rollout.log` | 自动更新回滚日志 |
| `/home/ubuntu/kimi-code-im-bot/` | Bridge 项目代码 |
| `/etc/systemd/system/kimi-bridge.service` | Bridge systemd unit |
