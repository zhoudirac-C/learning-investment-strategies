# qing agent 离线 → Qdrant 依赖链故障（2026-08-04 完整案例）

## 事故时间线

| 时间 | 事件 |
|---|---|
| 14:03:04 | 14:00"午盘"任务运行中，agent 日志出现 `Claims retrieval failed: Traceback (httpx ...)` + `Wiki retrieval failed` —— Qdrant 服务端不可达 |
| 14:06:40 | agent 仍在 reviewer 重试循环（`review_router: retry=1 → back to style_writer`），随后**进程崩溃** |
| 14:15:50 | 健康检查 cron 检测离线 → **自动重启 agent**（新 PID，日志出现 `日志初始化完成` + `[build_graph] compilation complete`） |
| 14:16+ | 用户问询；排查发现 **Qdrant 服务端也挂了**（6333 无监听，`curl` exit 7） |
| ~14:17 | 手动重启 Qdrant，两个 collection 数据完好 |

## 因果链

```
Qdrant 服务端挂（6333 无监听）
  → agent Claims/Wiki 检索失败（httpx 连接错误 traceback，仅 WARNING 不致命）
  → 任务缺检索上下文，卡在 reviewer 重试循环
  → agent 进程崩溃（原因未完全定位，可能与任务拖垮有关）
  → 健康检查 cron（*/15）自动拉起 agent
```

**关键洞察**：agent 被自动重启 ≠ 系统恢复。Qdrant 没起来之前 agent 检索仍然全挂，后续任务还会失败。所以"agent 离线"诊断必须**先查 Qdrant**。

## 诊断命令（按序）

```bash
# 1. Qdrant 服务端
curl -s -m 5 localhost:6333/collections   # exit 7 = 连接拒绝 = 挂
ss -tlnp | grep 6333                       # 无输出 = 未监听

# 2. agent
ps aux | grep uvicorn
ss -tlnp | grep 8000

# 3. 健康检查 cron 自愈证据（*.md 输出文件）
ls -lt ~/.hermes/cron/output/2a0889fa52d9/
# 文件内容含:
#   ❌ Qing-Agent 离线，正在自动重启...
#   Qing-Agent 已启动 (PID xxx)
# 正常轮次输出 "Status: silent (empty output)"

# 4. agent 崩溃前最后活动
tail -50 ~/learning-investment-strategies/logs/qing-agent.log
grep -n -E "Traceback|ERROR|CRITICAL" ~/learning-investment-strategies/logs/qing-agent.log | tail
```

## Qdrant 重启（Hermes 内正确姿势）

**坑**：`nohup ./bin/qdrant > /tmp/qdrant.log 2>&1 &` 会被 Hermes terminal 拒绝：
`Foreground command uses shell-level background wrappers (nohup/disown/setsid). Use terminal(background=true)`

**正确**：
1. `terminal(background=true)`: `cd ~/learning-investment-strategies && exec ./bin/qdrant > /tmp/qdrant.log 2>&1`
2. `sleep 6` 后验证：`curl -s localhost:6333/collections` → `{"result":{"collections":[{"name":"qing_claims"},{"name":"qing_knowledge"}]}}`
3. 验证 agent：`curl -s http://127.0.0.1:8000/health` → `{"status":"ok"}`

数据持久化在 RocksDB `./storage/`，重启不丢。

## 备注

- Qdrant 崩溃根因未定位（无 OOM 记录可查，dmesg 无权限）。若复发：优先看 `/tmp/qdrant.log` 尾部 + 系统内存。
- 受影响任务会留下 `last_status=error` + `last_delivery_error` 记录（当时还是 weixin 投递报 iLink 限流，需注意区分：**delivery error ≠ 任务失败**）。
- 14:00 任务当天失败无输出，恢复后下个时段任务自然恢复，无需补跑（除非用户要求）。
