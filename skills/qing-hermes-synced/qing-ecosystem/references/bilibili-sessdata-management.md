# Bilibili SESSDATA 管理

## 存储位置
SESSDATA 保存在 `~/.hermes/bilibili_sessdata.txt`，格式为 `hash,timestamp,hash`。

## 使用方法
```bash
cd ~/learning-investment-strategies
.venv/bin/python scripts/fetch_bilibili_up_v2.py \
  --sessdata "$(cat ~/.hermes/bilibili_sessdata.txt)"
```

## 过期检查
每日 08:30 和 20:30 自动运行 `~/.hermes/scripts/check_bilibili_cookie.sh`（cron job "B站Cookie过期提醒"），过期前 7 天发提醒。

## 换新流程

用户发送"更新b站cookie" → 按以下优先级处理：

**首选：自动刷新脚本**（二维码过期自动重发，无需手动重启）
```bash
cd /home/ubuntu/.hermes/skills/qing/qing-ecosystem
python3 scripts/qr_login_auto.py
```
脚本持续运行直至用户成功扫码+确认。二维码每3分钟过期后自动更新，用户无需反复要求"再发一次"。

**备选：单次脚本**（每次需手动重启）
用户发送"更新b站cookie" → Agent 发二维码 → 用户扫码 → 新 SESSDATA 自动保存到 `~/.hermes/bilibili_sessdata.txt`。

**⚠️ 用户必须完成两步**：扫码 + 在手机上点「确认登录」。仅扫码不确认不会生效。

**⚠️ API格式变更（2026年7月）**：B站 QR登录 API 不再通过 `data.cookie_info.cookies` 返回 SESSDATA，改为嵌入 `data.url` 的 query 参数中。`bilibili_qr_login.py`（2026-07-29 已修复）和 `qr_login_auto.py` 均兼容两种格式。

## 注意：SESSDATA 有效 ≠ API 可用
即使 SESSDATA 未过期（`nav` API 返回 `isLogin: True`），动态 feed 仍可能返回 **412 Precondition Failed**。
这是 B站 反爬机制升级所致（需 wbi 签名），非登录状态问题。
详见 `bilibili-api-412-troubleshooting.md`。

## Crontab 参考
cron job ID: `51a82ca795b7`，schedule: `30 8,20 * * *`，no_agent=true，script=`check_bilibili_cookie.sh`。
