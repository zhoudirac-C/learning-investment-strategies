# Kimi Bridge 恢复案例（2026-08-06 实测）

背景：8/5 清理 kimi 组件时把 `/home/ubuntu/kimi-code-im-bot` 整个代码目录删了（只留 `~/.kimi-code-im-bot/` 缓存）。8/6 用户要求"用 systemd 启动 bridge，但把 bridge 所有定时任务置为不可用"。

## 1. 现状确认（先别急着动手）

- `kimi-bridge.service` 存在于家目录（8/5 保留），但 `/etc/systemd/system/` 无此 unit → 从未正式安装
- `/home/ubuntu/kimi-code-im-bot` 不存在（代码被删）→ 不能直接 systemctl start
- `~/.kimi-code/bin/kimi` 存在且可运行（v0.33.0）→ 二进制已恢复（bash_history 显示 8/6 重跑过 `curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash` + `kimi login`）
- `~/.kimi-code-im-bot/feishu/credentials.json` 不存在 → 飞书凭据被删

排查顺序建议：服务文件 → 代码目录 → 二进制 → 凭据文件，四者状态都摸清再动。

## 2. 代码恢复（私有仓库 SSH clone）

```bash
# 验证 SSH 授权
ssh -T git@github.com   # → Hi zhoudirac-C! You've successfully authenticated

# HTTPS 尝试失败记录（两种都 404/要密码）：
#   curl https://github.com/zhoudirac-C/kimi-code-im-bot → HTTP 404
#   git clone https://... → fatal: could not read Username
#   GitHub API /repos/zhoudirac-C/kimi-code-im-bot → Not Found（私有仓库未认证）
# 用户 zhoudirac-C 存在（public_repos: 4），kimi-code-im-bot 是私有 → 用 SSH

git clone --depth 1 git@github.com:zhoudirac-C/kimi-code-im-bot.git /home/ubuntu/kimi-code-im-bot
cd /home/ubuntu/kimi-code-im-bot
pnpm install   # 3s；esbuild/protobufjs build scripts ignored 是正常 warning
pnpm build     # tsc → dist/main.js，exit 0
```

项目结构要点：`src/main.ts`（入口）、`src/cron/`（scheduler/store/runner）、`src/adapters/feishu/`、`src/cli/cron.ts`（定时任务管理 CLI）、`start.sh`。

## 3. systemd 服务文件

源文件 `/home/ubuntu/kimi-bridge.service` 原本指向 `WorkingDirectory=/home/ubuntu/kimi-code-im-bot` + `ExecStart=/usr/bin/node .../dist/main.js`——代码恢复后原文件直接可用，只需补充：

- `CRON_ENABLED=false`（用户要求禁用全部定时任务）
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET`（从 `~/.hermes/.env` 读取，防扫码卡死）

```bash
APP_ID=$(grep -oE 'FEISHU_APP_ID=.*' ~/.hermes/.env | cut -d= -f2)
APP_SECRET=$(grep -oE 'FEISHU_APP_SECRET=.*' ~/.hermes/.env | cut -d= -f2)
# 写入服务文件 Environment=FEISHU_APP_ID=${APP_ID} 等
sudo cp /home/ubuntu/kimi-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kimi-bridge.service
```

## 4. 验证

```bash
sudo systemctl status kimi-bridge.service   # Active: active (running)，Main PID node + 子进程 kimi acp
journalctl -u kimi-bridge.service -n 20
# 关键日志：
#   [FeishuWs] Using credentials from .env
#   [FeishuWs] Connection status: {"state":"connected",...}
#   Bridge HTTP server listening on 127.0.0.1:3000
#   Starting Kimi ACP process: /home/ubuntu/.kimi-code/bin/kimi acp
#   ACP initialized → ACP authenticated
```

定时任务禁用确认：
- `grep CRON_ENABLED /etc/systemd/system/kimi-bridge.service` → `CRON_ENABLED=false`
- `cat ~/.kimi-code-im-bot/cron/jobs.json` → `{"jobs": []}`（双保险）

## 5. 坑位清单

| 坑 | 说明 |
|---|---|
| 私有仓库 HTTPS 404 | 网页/API 都 404 = 私有仓库未认证，不是 URL 错；用 SSH |
| 飞书凭据缺失阻塞启动 | performFeishuQrAuth 扫码等人工，headless 卡死；预置 env 或 credentials.json |
| Node 版本 WARN | engines >=24.15 但 v22 实测正常，忽略 |
| 服务文件改了不 reload | Environment 不生效；必须 `sudo systemctl daemon-reload` |
| pnpm build scripts 忽略 | esbuild 等 warning 正常，tsc 构建不受影响 |
