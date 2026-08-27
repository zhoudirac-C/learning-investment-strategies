---
name: kimi-bridge-ops
description: >-
  Kimi Code IM Bridge (kimi-code-im-bot) 运维：systemd 服务启停/状态、
  代码恢复（私有仓库 SSH clone）、构建、定时任务禁用（CRON_ENABLED）、
  飞书凭据复用。Use when: "启动bridge"、"bridge起不来"、"停掉bridge定时任务"、
  "恢复kimi bridge"、"kimi-bridge.service"。
category: qing
---

# kimi-bridge-ops

Kimi Code IM Bridge（把飞书/企微/个人微信接入 Kimi Code CLI 的桥接服务）运维手册。

## 关键路径

| 项 | 路径 |
|---|---|
| 代码仓库 | `/home/ubuntu/kimi-code-im-bot`（私有仓库 `git@github.com:zhoudirac-C/kimi-code-im-bot.git`） |
| 服务文件源 | `/home/ubuntu/kimi-bridge.service`（家目录） |
| systemd unit | `/etc/systemd/system/kimi-bridge.service` |
| 数据/缓存 | `~/.kimi-code-im-bot/`（cron/jobs.json、feishu/credentials.json、logs/） |
| kimi 二进制 | `~/.kimi-code/bin/kimi`（`kimi login` 授权，v0.36.1） |
| 定时任务存储 | `~/.kimi-code-im-bot/cron/jobs.json` |

## 日常运维命令

```bash
sudo systemctl status|restart|stop kimi-bridge.service
journalctl -u kimi-bridge.service -f
```

## 代码恢复：私有仓库必须 SSH clone

8/5 清理 kimi 组件时连代码目录一起删了（只剩 `~/.kimi-code-im-bot/` 缓存）。恢复：

1. **验证 SSH 授权**：`ssh -T git@github.com` → `Hi zhoudirac-C! You've successfully authenticated`
2. **必须用 SSH 协议**：`git clone --depth 1 git@github.com:zhoudirac-C/kimi-code-im-bot.git /home/ubuntu/kimi-code-im-bot`
   - ⚠️ HTTPS 会失败：网页 404、git 要用户名密码、GitHub API 对私有仓库返回 Not Found（未认证时）。这是**私有仓库**的典型表现，不是 URL 写错
3. 构建：`cd /home/ubuntu/kimi-code-im-bot && pnpm install && pnpm build`（tsc → dist/main.js）
   - Node engines 要求 >=24.15，本机 v22 实测构建/运行正常（仅 WARN），别为版本卡住

## systemd 服务安装

```bash
sudo cp /home/ubuntu/kimi-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kimi-bridge.service
```

服务文件关键 Environment（改完必须 daemon-reload）：
- `KIMI_ENGINE=acp` + **引号包裹** `Environment="KIMI_ACP_COMMAND=/home/ubuntu/.kimi-code/bin/kimi acp"`（⚠️ systemd Environment= 值含空格必须引号包裹，否则 acp 被截断 → ACP 永不初始化，bridge 收消息不回复）+ `KIMI_ACP_PERMISSION_MODE=auto`
- **`KIMI_ACP_MODEL_ALIAS=kimi-code/k3`** ← 模型切换：main.ts 读此 env → 拼 `-m <alias>`；alias 须匹配 `~/.kimi-code/config.toml` 注册的模型 key（k3/k3-256k/kimi-for-coding…）
- `FEISHU_ENABLED=true` + `FEISHU_CONNECTION_MODE=websocket`（长连接，无需公网 URL）
- `BRIDGE_PORT=3000` + `BRIDGE_HOST=127.0.0.1`
- **`CRON_ENABLED=false`** ← 禁用全部定时任务的总开关

模型切换双保险：bridge env（`KIMI_ACP_MODEL_ALIAS`）+ CLI 兜底（`~/.kimi-code/config.toml` 的 `default_model`，`kimi -m` 默认读它）。部署前可 `kimi -m <alias> -p "test"` 非交互验证模型可用。

## 思考力度（effort）切换：KIMI_MODEL_THINKING_EFFORT

**"k3 max" ≠ 独立模型**（8/16 实战确认）。config.toml 注册 4 个模型：`kimi-code/k3`（K3，1M ctx，`support_efforts=[low,high,max]`，`default_effort=high`）、`kimi-code/k3-256k`（256k，同上）、`kimi-code/kimi-for-coding`（K2.7）、`kimi-code/kimi-for-coding-highspeed`。`max` 是 K3 的**思考力度档位**（请求级参数），不是模型名——用户说"k3 max"= K3 模型 + max effort。

- `kimi acp` 子命令**没有** CLI effort 选项（`--help` 只有 `--login`）
- effort 覆盖唯一通道 = 环境变量 **`KIMI_MODEL_THINKING_EFFORT`**：请求级注入 provider（二进制字符串确认 `resolveKimiEnvThinkingEffort`，"The override intentionally bypasses support_efforts"），**ACP 模式同样生效**。合法值 low/high/max（K3 支持）；设 `off` 关闭 thinking
- 操作流程：服务文件加 `Environment=KIMI_MODEL_THINKING_EFFORT=max` → `sudo cp` 到 /etc/systemd/system → `daemon-reload` → `restart` → 验证 `systemctl show kimi-bridge.service -p Environment | grep EFFORT` + journalctl 看 `Starting Kimi ACP process` 正常
- 回滚 = 删掉该行重启；不设 env 时走 config.toml 的 `default_effort=high`（全局改 config.toml 的 default_effort 会同时影响手动 kimi CLI 会话，桥接隔离优先用 env）
- 成本（8/16 实测）：max 档思考 token 显著更高、响应明显变慢；IM 场景用户试用后改回 high——默认 high，max 只适合复杂任务临时切

启动成功日志特征（journalctl）：
- `[FeishuWs] Connection status: {"state":"connected",...}` = 飞书 ws 连上
- `Starting Kimi ACP process` → `ACP initialized` → `ACP authenticated` = kimi acp 就绪
- `Bridge HTTP server listening on 127.0.0.1:3000`

## ⚠️ cwd 双层架构（kimi 工作目录在哪）

- **spawn 级**：`KIMI_ACP_CWD` 只决定 kimi 进程启动 cwd
- **session 级（真正生效）**：`session-manager.ts` 创建 session 时 `createSession(workspace.id, cwd)` → ACP `session/new { cwd }`。**cwd 默认是 workspace 隔离目录** `{KIMI_WORKSPACE_ROOT}/{platform}/{chatType}/{chatId}`（每个 chat 独立空目录）——kimi 回答"当前工作目录"时用的是这个！
- 8/7 已改：`session-manager` 新增 `sessionCwd?` 选项（main.ts 传 `config.kimiEngine.acpCwd`），session 级 cwd 指向项目根；workspace 目录仍保留做会话隔离
- 排查"kimi 说在空目录/看不到项目文件"→ 查 session 级 cwd，不是 KIMI_ACP_CWD

## 禁用全部定时任务（用户常用要求）

- **总开关**：服务文件 Environment 加 `CRON_ENABLED=false` → scheduler 完全不启动（scheduler 只跑 jobs.json 里 `enabled: true` 的任务，src/cron/scheduler.ts）
- **双保险**：`CRON_ENABLED=false` + jobs.json 置空 `{"jobs": []}`
- 管理 CLI：`pnpm cron add/list/pause/resume/remove`（src/cli/cron.ts）

## 飞书凭据：独立机器人优先（不复用 Hermes app）

- 凭据优先级：env `FEISHU_APP_ID/FEISHU_APP_SECRET` > `~/.kimi-code-im-bot/feishu/credentials.json` > 都没有 → **触发扫码创建机器人（performFeishuQrAuth）阻塞启动**，headless 上会卡住
- ⚠️ **凭据错配坑（8/7 实战）**：服务文件里显式写 `FEISHU_APP_ID/FEISHU_APP_SECRET`（哪怕写的是 Hermes 的）会**覆盖** credentials.json 的独立机器人 → bridge 连错 app → 用户给独立机器人发消息 bridge **收不到**（日志只有 reaction 事件、零 receive_v1）。修复：服务文件**不设** FEISHU_APP_ID/SECRET，只留 `FEISHU_CREDENTIAL_PATH` 指向 credentials.json。部署后验证：日志应显示 `ensureCredentials: appId=(empty)` + `Reading credentials from: ...credentials.json`（出现 `appId=cli_xxx` 即被 env 覆盖）
- （历史做法，已废弃）8/5 曾把 `~/.hermes/.env` 的 FEISHU_APP_ID/SECRET 写进服务文件（"复用 Hermes 最快"）→ 8/6 用户硬性要求独立机器人后应移除；8/7 实测此做法导致凭据错配、收不到消息，**不要再把 Hermes 凭据写进服务文件**
- 手动启动测试（防 Hermes env 污染，参考 start.sh 的 `env -u` 技巧）：
  ```bash
  env KIMI_ENGINE=acp KIMI_ACP_COMMAND="/home/ubuntu/.kimi-code/bin/kimi acp" \
      KIMI_ACP_CWD=/home/ubuntu/kimi-code-im-bot KIMI_ACP_PERMISSION_MODE=auto \
      FEISHU_ENABLED=true FEISHU_CONNECTION_MODE=websocket \
      FEISHU_APP_ID="$APP_ID" FEISHU_APP_SECRET="$APP_SECRET" \
      BRIDGE_PORT=3000 BRIDGE_HOST=127.0.0.1 LOG_LEVEL=info CRON_ENABLED=false \
      node dist/main.js
  ```

## kimi 工作目录机制（ACP session cwd ≠ 进程 cwd）

**现象**：kimi 回答"当前工作目录"是 `{KIMI_WORKSPACE_ROOT}/feishu/p2p/{chat_id}` 空目录，而不是 `KIMI_ACP_CWD`。

**根因（代码层）**：`src/bridge/session-manager.ts` 创建 ACP session 时把 cwd **硬编码**为 workspace 隔离目录：
```ts
const workspaceRoot = join(this.workspaceRoot, ctx.platform, ctx.chatType, ctx.chatId);
const session = await this.client.createSession(workspace.id, workspaceRoot);  // ← session/new 的 cwd
```
- `KIMI_ACP_CWD` 只决定 spawn 的 kimi 进程 cwd（acp-client.ts `spawn(cmd, args, { cwd: options.cwd })`）
- **session 级 cwd 由 createSession 参数决定**，覆盖进程 cwd → 想改 kimi 实际工作目录必须改这里，改 env/服务文件无效

**修复（2026-08-07 已实施）**：thread `sessionCwd` 参数，fallback 到 workspaceRoot：
- `session-manager.ts`：构造函数加 `private sessionCwd?: string`，`createSession(workspace.id, this.sessionCwd ?? workspaceRoot)`
- `core.ts`：`BridgeCoreOptions` 加 `sessionCwd?: string`，构造 SessionManager 传入
- `main.ts`：`new BridgeCore({ ..., sessionCwd: config.kimiEngine.acpCwd })`
- 构建 `pnpm build` 后重启；验证：给 bridge 发消息问 cwd 应返回项目根（重启后内存 session 清空，新消息即新 session；旧 session 2h 超时或 `/new` 重置）
- workspace 隔离目录仍会创建（会话管理用），只是 session cwd 独立

**注意**：`acp-client.ts` 的 `createSession/getSession` 返回的 `agent_config.model` **写死 `kimi-code/kimi-for-coding`**——只是 session 元数据声明，不影响实际模型（由 `-m <alias>` 决定），排查模型问题时别被它误导。

## 坑位

- **私有仓库 HTTPS 404 / API Not Found ≠ 仓库不存在** → 先试 SSH（`ssh -T git@github.com` 验证授权）
- **飞书凭据缺失会阻塞启动等扫码** → headless 环境必须预置凭据：优先用独立机器人 `credentials.json`（服务文件只留 `FEISHU_CREDENTIAL_PATH`），**不要**把 Hermes 的 FEISHU_APP_ID/SECRET 写进服务文件（见"飞书凭据"节的凭据错配坑）
- **esbuild/protobufjs build scripts 被 pnpm 忽略**是正常 warning，不影响 tsc 构建
- **改服务文件后必须 `sudo systemctl daemon-reload`** 否则 Environment 不生效

## 详细恢复案例

2026-08-06 完整恢复流程（含日志验证）见 `references/kimi-bridge-restore-systemd.md`。
