# Cron 脚本超时诊断手册

> 针对 `qing_stock_monitor_agent.py` 及其 wrapper 脚本的超时问题诊断与修复。

---

## 症状

Cron job 报错：
```
Script timed out after 120s: /home/ubuntu/.hermes/scripts/qing_stock_monitor_agent.py
```

---

## 调用链

```
qing_stock_monitor_agent.py (wrapper)
  → hermes_stock_monitor_agent.py
    → fetch_json_context()
      → stock_monitor.py --agent-json-context --ignore-trading-time
        → run_tick()
          → find_agent_analysis_trigger()  # 查 schedule / alerts
          → 若 trigger=None 且 alerts=空 → 返回 ""
    → call_qing_agent()
      → POST http://localhost:8000/analyze/trigger
      → 默认超时 180s，重试 3 次
    → 输出结果
```

---

## 根因分析

### 根因 A：Qing-Agent 服务无响应（最常见）

**判断**：`fetch_json_context()` 返回非空 JSON，但 `call_qing_agent()` 阻塞。

**验证**：
```bash
# 1. 测试 Qing-Agent 端点
curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"超时诊断","session_id":"timeout-diag","analysis_type":"market"}'
# 无响应或超时 → Qing-Agent 挂死

# 2. 检查进程
pgrep -a -f "gunicorn"
ss -tlnp | grep 8000
```

**修复**：重启 Qing-Agent（见 `qing-agent-service-operations.md`）。

### 根因 B：不在 schedule 时间点且无 alerts

**判断**：`fetch_json_context()` 返回 `None`，脚本直接 `return 0`。

**验证**：
```bash
cd ~/learning-investment-strategies
python3 -u scripts/stock_monitor.py --agent-json-context --ignore-trading-time 2>&1 | cat
# 空输出 → 无 trigger
```

**这不是超时根因**——空输出会在毫秒级返回，不会触发 120s 超时。但 cron 会报告 "script produced no output"。

### 根因 C：行情获取阻塞

**判断**：`fetch_quotes_with_fallback()` 在网络层阻塞。

**验证**：
```bash
cd ~/learning-investment-strategies
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import fetch_quotes_with_fallback, collect_quote_targets, load_monitor_config
import time
config = load_monitor_config()
targets = collect_quote_targets(config)
start = time.time()
result = fetch_quotes_with_fallback(targets)
elapsed = time.time() - start
print(f'source={result[\"source\"]}, quotes={len(result[\"quotes\"])}/{len(targets)}, elapsed={elapsed:.1f}s')
"
```

**修复**：数据源降级链已修复（腾讯→新浪→东财），见 `references/tencent-sina-eastmoney-fallback-chain.md`。

### 根因 D：Cron 外层超时 < 脚本内超时

**判断**：脚本内部 `QING_AGENT_TIMEOUT=180s`，但 cron 外层只给 120s。

**验证**：
```bash
# 检查 cron 配置
grep "qing_stock_monitor_agent" ~/.hermes/cron/cron.yaml
# 看 timeout 字段
```

**修复**：
1. 调大 cron timeout：
   ```yaml
   timeout: 200  # 从 120 改为 200
   ```
2. 或调小脚本内部超时：
   ```bash
   export QING_AGENT_TIMEOUT=30
   ```

---

## 快速诊断流程

```
1. 手动运行 wrapper 脚本，加 time 计时：
   time python3 scripts/hermes_stock_monitor_agent.py
   
   ├─ < 5s 返回 → 不是超时问题，是 schedule 不匹配（见 cron-pipeline-architecture.md）
   ├─ 5s-30s 返回 → 正常范围
   ├─ 30s-120s 返回 → 行情获取慢或 Qing-Agent 响应慢
   └─ >120s 被 kill → 确认是超时问题

2. 分段计时定位瓶颈：
   # 段 1：stock_monitor.py 单独跑
   time python3 -u scripts/stock_monitor.py --agent-json-context --ignore-trading-time
   
   # 段 2：直接测 Qing-Agent
   time curl -s --max-time 60 -X POST http://localhost:8000/analyze/trigger ...
   
   ├─ 段 1 慢 → 行情获取问题
   ├─ 段 2 慢 → Qing-Agent 问题
   └─ 都正常 → wrapper 逻辑问题（罕见）

3. 检查 cron 日志：
   ls -lt ~/.hermes/cron/output/<job_id>/
   cat ~/.hermes/cron/output/<job_id>/<latest>.md
```

---

## 预防措施

1. **Cron timeout ≥ 脚本内超时 + 20s 缓冲**
   ```yaml
   # cron.yaml
   timeout: 200  # QING_AGENT_TIMEOUT=180 + 20s
   ```

2. **脚本内超时环境变量**
   ```bash
   # 在 wrapper 脚本或 cron env 中设置
   export QING_AGENT_TIMEOUT=30
   export QING_AGENT_MAX_RETRIES=2
   ```

3. **Qing-Agent 健康检查前置**
   在 cron 执行前加 health check：
   ```bash
   curl -s --max-time 5 http://localhost:8000/health || exit 0
   ```

4. **监控 fallback 率**
   定期检查 cron 输出是否含 `[Qing-Agent ✗ FALLBACK]`：
   ```bash
   for dir in ~/.hermes/cron/output/*/; do
     latest=$(ls -t "$dir"/*.md 2>/dev/null | head -1)
     [ -n "$latest" ] && grep -l "FALLBACK" "$latest" && echo "  $(basename $dir)"
   done
   ```
