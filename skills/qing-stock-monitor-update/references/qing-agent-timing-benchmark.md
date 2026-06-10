# Qing-Agent 完整链路耗时基准

> 记录时间：2026-06-10
> 测试环境：Ubuntu 22.04, Python 3.12, gunicorn 单 worker, Qdrant 本地模式
> 数据来源：多次 `curl /analyze/trigger` 实测 + `time` 命令

## 完整链路拆解

```
┌─────────────────────────────────────────────────────────────┐
│  ① 行情拉取 (fetch_quotes_with_fallback)                    │
│     腾讯(gtimg) → 新浪(hq.sinajs.cn) → 东财(push2)          │
│     耗时: ~12-18s (中位数 ~15s)                              │
│     瓶颈: 腾讯 API 响应时间 + 三源合并逻辑                    │
├─────────────────────────────────────────────────────────────┤
│  ② HTTP POST /analyze/trigger                               │
│     客户端 urlopen → gunicorn → UvicornWorker               │
│     → LangGraph 管线 (market_analyst → synthesize           │
│       → style_writer → reviewer)                            │
│     耗时: ~45-65s (中位数 ~52s)                              │
│     瓶颈: LLM 推理 (30-50s) + 向量检索 (5-10s)               │
├─────────────────────────────────────────────────────────────┤
│  ③ 响应处理 (hermes_stock_monitor_agent.py wrapper)         │
│     JSON 解析 → daily_state 提取 → 文件写入 → 日志           │
│     耗时: ~3-8s                                              │
│     瓶颈: 文件 I/O + JSON 序列化                              │
├─────────────────────────────────────────────────────────────┤
│  ④ Hermes cron 输出格式化                                    │
│     Markdown 渲染 → 微信推送                                 │
│     耗时: ~2-5s (在 cron scheduler 层)                       │
└─────────────────────────────────────────────────────────────┘
                         总计: ~70-75s
```

## 各阶段实测数据

### 行情拉取阶段

```bash
cd ~/learning-investment-strategies
python3 -c "
import sys, time; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import fetch_quotes_with_fallback, collect_quote_targets, load_monitor_config
config = load_monitor_config()
targets = collect_quote_targets(config)
t0 = time.time()
result = fetch_quotes_with_fallback(targets)
t1 = time.time()
print(f'time={t1-t0:.1f}s, source={result[\"source\"]}, quotes={len(result[\"quotes\"])}/{len(targets)}')
"
```

**典型输出**：
```
time=14.2s, source=tencent_gtimg, quotes=184/184, errors=[]
```

### HTTP API 阶段

```bash
curl -s -w "\ntime_total=%{time_total}\n" --max-time 200 \
  -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"测试耗时","session_id":"timing-test","analysis_type":"market"}' \
  | tail -1
```

**典型输出**：
```
time_total=51.847
```

### 端到端（含 wrapper）

```bash
cd ~/learning-investment-strategies
time python3 scripts/hermes_stock_monitor_agent.py
```

**典型输出**：
```
real    1m12.341s
user    0m2.156s
sys     0m0.483s
```

## 超时配置建议

基于 70-75s 基准，各层级超时应满足：

```
LLM 推理超时 (模型自身)     : 60s  (固定，不可调)
gunicorn worker 超时        : 120s (≥ LLM + 缓冲)
QING_AGENT_TIMEOUT          : 180s (≥ 完整链路 + 2×重试缓冲)
CRON_WRAPPER_TIMEOUT        : 200s (≥ QING_AGENT + 脚本开销)
HERMES_CRON_SCRIPT_TIMEOUT  : 300s (≥ CRON_WRAPPER + 20s 安全边距)
```

**关键不等式**：
```
HERMES_CRON_SCRIPT_TIMEOUT ≥ QING_AGENT_TIMEOUT + 60
QING_AGENT_TIMEOUT ≥ 90 (实测中位数 52s + 50% 缓冲)
```

## 异常耗时诊断

| 现象 | 可能原因 | 排查命令 |
|------|---------|---------|
| >120s | Qdrant 向量检索慢 / 首次加载 | `curl /health` 检查 Qdrant 状态 |
| >180s | gunicorn worker 崩溃重启 | `tail -20 /tmp/qing-agent.log` |
| 间歇性 30s+ | 东财限流导致行情拉取阻塞 | 检查 `fetch_quotes_with_fallback` 日志 |
| 始终 >100s | Neo4j 查询慢 / 关系图过大 | `cypher-shell -u neo4j -p xxx "MATCH (c:Claim) RETURN count(c)"` |

## 优化方向

1. **行情缓存**：同一 cron tick 内多次调用时复用行情数据（当前每次重新拉取）
2. **向量检索预热**：Qdrant 冷启动后首次查询慢，可考虑 cron 前预热
3. **LangGraph 并行化**：`market_analyst` 和 `stock_analyst` 可并行执行（当前串行）
4. **gunicorn 多 worker**：Qdrant 本地模式限制为单 worker，但可考虑 Qdrant Server 模式解锁多 worker
