# Qing-Agent 服务运维手册

> 日常运维 Qing-Agent 服务的速查手册。涵盖启动、重启、健康检查、故障诊断。

---

## 快速状态检查

```bash
# 1. 进程检查
pgrep -a -f "gunicorn"
# 期望输出：master (PID X) + worker (PID Y)
# 如果看到 uvicorn → 说明还在用旧启动方式，需迁移

# 2. 端口检查
ss -tlnp | grep 8000

# 3. 健康检查（仅确认进程存活）
curl -s http://localhost:8000/health
# {"status":"ok","version":"0.1.0"}

# 4. 实际端点测试（必须测这个）
curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"健康检查","session_id":"health-001","analysis_type":"market"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('final_output') else 'EMPTY')"
```

---

## 启动 / 重启

```bash
# 1. 杀旧进程（同时杀 uvicorn 和 gunicorn，防混用）
kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null
kill $(pgrep -f "gunicorn") 2>/dev/null
sleep 2

# 2. 确认端口释放
ss -tlnp | grep 8000 || echo "Port 8000 free"

# 3. 启动（必须在 repo root，.env 才能被 pydantic 读到）
cd ~/learning-investment-strategies
nohup .venv/bin/gunicorn qing_investment.agent.main:app \
  -w 1 -k uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8000 \
  --timeout 120 --keep-alive 5 \
  > /tmp/qing-agent.log 2>&1 &

# 4. 验证
sleep 3
curl -s --max-time 5 http://localhost:8000/health && echo ""
curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"重启验证","session_id":"restart-check","analysis_type":"market"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('RESTART OK' if d.get('final_output') else 'STILL BROKEN')"
```

---

## 故障诊断决策树

```
├─ 微信没收到消息
│  ├─ cron output 文件 0 bytes → 脚本 stdout 为空
│  │  ├─ 检查 schedule 对齐（strategy_pack time vs cron schedule）
│  │  └─ 直接运行 wrapper 脚本看输出
│  ├─ 输出有内容但无 claims 引用 → 可能走 fallback
│  │  └─ 扫 blast radius（见下方）
│  └─ 输出正常 → iLink 限流或 delivery 问题
│
├─ 分析质量下降（无 claims 引用、方向词过期）
│  ├─ 扫 blast radius → 有 FALLBACK 标记 → Qing-Agent 挂死
│  │  └─ 重启服务（见上方）
│  └─ 无 FALLBACK 标记 → 可能是 claims 未入库或 prompt 问题
│
└─ /health OK 但 /analyze/trigger 超时
   ├─ 单请求测试 >30s → LangGraph 管线卡死（检查日志）
   └─ 单请求正常但 cron 超时 → 级联超时（已修复：120s + 重试）
```

---

## Blast Radius 扫描

```bash
# 检查最近 cron 输出是否走 fallback
# 成功标记：[Qing-Agent ✓]  失败标记：[Qing-Agent ✗ FALLBACK] 或旧版 [qing-agent fallback
for dir in ~/.hermes/cron/output/*/; do
  latest=$(ls -t "$dir"/*.md 2>/dev/null | head -1)
  [ -n "$latest" ] && grep -lE "Qing-Agent . FALLBACK|qing-agent fallback" "$latest" && echo "  ↳ $(basename $dir)"
done
```

---

## 日志查看

```bash
# 实时日志
tail -f /tmp/qing-agent.log

# 最近错误
grep -i "error\|exception\|timeout" /tmp/qing-agent.log | tail -20

# 启动记录
grep "Starting gunicorn\|Worker ready" /tmp/qing-agent.log
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `QING_AGENT_TIMEOUT` | 120 | 脚本调用 /analyze/trigger 的超时（秒） |
| `QING_AGENT_MAX_RETRIES` | 3 | 失败重试次数 |
| `QING_AGENT_URL` | http://localhost:8000/analyze/trigger | Agent 端点 |

---

## 参数速查

| 参数 | 含义 |
|------|------|
| `-w 1` | 1 个 worker（Qdrant 本地模式限制，不可改大） |
| `-k uvicorn.workers.UvicornWorker` | 每个 worker 用 Uvicorn 处理 ASGI |
| `--timeout 120` | worker 处理请求的最大时间（秒） |
| `--keep-alive 5` | HTTP keep-alive 连接保持 5s |
