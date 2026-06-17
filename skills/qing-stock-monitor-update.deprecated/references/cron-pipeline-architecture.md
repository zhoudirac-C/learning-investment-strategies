# Cron 管线架构（2026-06-09 澄清）

> **触发**：本次会话中 Agent 误以为修改 cron job 的 `prompt` 字段能传递给 qing-agent，用户纠正。

## 实际调用链

```
cron job (prompt: 简洁 fallback 文本)
  → qing_stock_monitor_agent.py
    → stock_monitor.py --agent-json-context  拉行情 + 组装JSON
    → POST qing-agent /analyze/trigger       调本地 LangGraph Agent
      → parse_query → retrieve_knowledge → market_analyst → ...
      → market_analyst 节点使用 market_analyst.txt 作为 system prompt
      → style_writer 节点使用 style_writer.txt
      → 返回 final_output
    → 输出微信消息
```

## 关键陷阱

❌ **cron job 的 `prompt` 字段不传给 qing-agent。**
   qing-agent 通过 HTTP API 调用，使用自己的 LangGraph system prompt（`prompts/system/*.txt`）。
   cron prompt 只在 qing-agent 不可用时的 **fallback 文本路径** 生效。

✅ **修改 qing-agent 行为 → 改 `prompts/system/market_analyst.txt`（或对应节点 prompt）**

✅ **修改 cron 调用参数（如触发标题/原因）→ 改 `strategy_pack.yaml` 的 `agent_analysis_schedule`**

## 三条管线

| 管线 | 触发方式 | LLM | 改哪里 |
|------|---------|-----|--------|
| 手动更新 | 用户说"更新观察池" | qing-agent /chat | `qing-stock-monitor-update` SKILL.md |
| 定时分析 | 9个Cron定点触发 | qing-agent /analyze/trigger | `market_analyst.txt` + `agent_analysis_schedule` |
| 条件轮询 | Cron每5分钟no-agent | 无 | `stock_monitor.py` run_tick() 纯规则 |

> **注意**：15:20（收盘复盘）虽然和 9 个定时 cron 一样有 LLM 调用，但走的是 **Hermes 直调 LLM**（DeepSeek），不是 qing-agent。脚本 `qing_stock_monitor_daily_review.py` → `stock_monitor.py --daily-review-context` → 输出文本上下文 → Hermes cron agent 调 DeepSeek 分析。**不使用** `find_agent_analysis_trigger()` 也不检查 `agent_analysis_schedule`。这意味着它有两个独特的失败模式：
> 1. **DeepSeek API 流式断连**：API 接受连接但返回 0 bytes → agent.log 出现 "Stream stale for 180s" → cron 卡住直到 3 次重试耗尽（可能耗时 10 分钟+）。**不是配置问题**，是 DeepSeek 服务端问题。
> 2. **上下文过大**：`--daily-review-context` 输出的上下文可能 >5k tokens，DeepSeek 在处理大上下文时更容易触发流式断连。

## daily_state 写入链

```
market_analyst.txt 末尾要求输出 ```daily_state 代码块
  → qing-agent 在回复中生成
  → cron output 落盘 ~/.hermes/cron/output/<job_id>/
  → sync_daily_state.py 每5分钟扫描提取JSON
  → 写入 config/stock_monitor/daily_state.json
  → 下一节点 format_agent_analysis_context() 读取注入
```

## 相关文件

- `prompts/system/market_analyst.txt` — qing-agent 的 market_analyst system prompt
- `scripts/sync_daily_state.py` — daily_state 扫描写回
- `scripts/sync_claims_to_config.py` — claims→config 桥接
- `scripts/qing_stock_monitor_poll.py` — 条件驱动轮询入口

## 时间匹配陷阱：cron schedule ≠ agent_analysis_schedule → 静默空输出

**现象**：cron job 状态 `ok`，但输出文件 0 字节，微信未收到消息。

**完整调试链路**（2026-06-09 实战追踪）：

```
1. cron output 文件 /hermes/cron/output/<job_id>/  → 0 bytes
2. agent.log 关键字: "script produced no output, skipping AI call"
3. hermes_stock_monitor_agent.py → fetch_json_context() → stock_monitor.py --agent-json-context
4. stock_monitor.py run_tick() → find_agent_analysis_trigger()
   → is_scheduled_agent_analysis_time() 查 strategy_pack.yaml agent_analysis_schedule
   → time 字段: "14:50" 但 cron 运行在 14:55 → 不匹配 → 返回 None
5. agent_trigger=None + new_alerts=空 → run_tick() 返回 ""
6. wrapper 脚本收到空 stdout → return 0
7. cron: "script produced no output" → [SILENT] → 跳过发送
```

**根因**：`strategy_pack.yaml` 的 `agent_analysis_schedule` 中 `time` 字段与 cron job 的 `schedule` 分钟数不一致。`find_agent_analysis_trigger()` 按 HH:MM 精确匹配，差一分钟就是 None。

**修复**：
```yaml
# strategy_pack.yaml — 确保与 cron schedule 一致
agent_analysis_schedule:
  - id: tail_condition
    time: '14:55'      # ← 必须与 cron "55 14 * * 1-5" 匹配
    name: 尾盘条件单
```

**预防**：创建/修改 cron job 时，必须同步检查 `strategy_pack.yaml` 的 `agent_analysis_schedule` 时间，以及 `src/qing_investment/stock_monitor.py` 的 `DEFAULT_AGENT_ANALYSIS_SCHEDULE`。

**三重对齐检查表**（2026-06-09 实战：发现 3 个 cron 因不对齐而空输出）：

| 时间 | cron schedule | strategy_pack time | DEFAULT time | 状态 |
|------|-------------|-------------------|-------------|------|
| 09:26 | `26 9 * * 1-5` | 09:26 | 09:26 | ✅ |
| 09:45 | `45 9 * * 1-5` | 09:45 | 09:45 | ✅ |
| 10:00 | `0 10 * * 1-5` | ❌ 缺失 | 10:00 | ⚠️ 需补 |
| 10:30 | `30 10 * * 1-5` | 10:30 (ID错) | 10:30 (ID不同) | ⚠️ ID需修 |
| 11:20 | `20 11 * * 1-5` | 11:20 | 11:20 | ✅ |
| 13:10 | `10 13 * * 1-5` | 13:10 | 13:10 | ✅ |
| 14:00 | `0 14 * * 1-5` | 14:00 | 14:00 | ✅ |
| 14:55 | `55 14 * * 1-5` | 14:50 ❌ | 14:55 | ⚠️ 需修 |
| 15:20 | `20 15 * * 1-5` | ❌ 缺失 | 15:20 | 独立路径 |

> **注意 15:20**：走 `qing_stock_monitor_daily_review.py` → `stock_monitor.py --daily-review-context`，**不经过** `find_agent_analysis_trigger()`，不检查 schedule。即使 strategy_pack 缺失 15:20 条目，也不影响输出。这是唯一不使用 schedule 匹配的看盘 cron。

## Cron 空输出诊断决策树

当用户报告「cron 跑了但微信没收到」：

```
├─ 0. cron list 检查 last_run / last_status / delivery_error
│
├─ 1. 输出文件检查：~/.hermes/cron/output/<job_id>/<timestamp>.md
│   ├─ 文件存在且 > 0 bytes → 内容已生成，问题在 delivery
│   │   └─ 看 delivery_error: "rate limited" → iLink 限流
│   └─ 文件 0 bytes 或不存在 → 输出未生成
│
├─ 2. agent.log 关键字定位：
│   ├─ "script produced no output, skipping AI call"
│   │   → 脚本 stdout 为空
│   │   ├─ --agent-json-context 路径：查三重对齐（schedule 不匹配）
│   │   └─ --daily-review-context 路径：查 format_daily_review_context()
│   │
│   └─ "Stream stale for 180s" / "peer closed connection"
│       → LLM API 断连（cron 在运行但 LLM 卡住）
│       → 这是 DeepSeek 服务端问题，非配置问题
│
├─ 3. 手动复现：直接运行 wrapper 脚本看 stdout
│   cd ~/learning-investment-strategies
│   .venv/bin/python scripts/hermes_stock_monitor_agent.py
│   → 空输出 = schedule 不匹配；有输出 = cron 环境问题
│
└─ 4. 时间匹配检查：grep agent_analysis_schedule strategy_pack.yaml
    → 确认 cron schedule 的分钟数与 strategy_pack 的 time 字段一致
```

## Qing-Agent 静默 fallback 诊断

**症状**：微信消息正常收到，但分析质量下降——无 claims 引用、方向词可能过期。Qing-Agent 实际未参与。

**原因**：`/health` 返回 200 但 `/analyze/trigger` 挂死。脚本等到 120s 超时后走 fallback → Hermes LLM 直接用原始监控数据生成分析。

**⚠️ 级联 fallback 风险（2026-06-10 确认，已修复）**：不是每次独立超时——一旦第一个 cron 请求的管线耗时超过 120s 触发超时，gunicorn worker 仍在后台继续处理（无中断机制）。后续 cron 到达时 worker 繁忙，排队等待 → 全部超时。**一次慢请求可以瘫痪全天 9 个 cron。**

**修复措施（2026-06-10 已实施）**：
1. **超时调大**：脚本默认 45s → **120s**（环境变量 `QING_AGENT_TIMEOUT` 可覆盖）
2. **指数退避重试**：3 次重试，间隔 1s/2s/4s
3. **uvicorn → gunicorn 单 worker**：获得进程崩溃自动重启、优雅关闭、统一日志
4. **成功/失败显式标记**：输出含 `[Qing-Agent ✓]` 或 `[Qing-Agent ✗ FALLBACK]`，blast radius 可扫

**超时调优**：管线 30s+，脚本默认 120s 已足够覆盖正常情况。若仍频繁集体 fallback：
```bash
export QING_AGENT_TIMEOUT=120  # 置入 .bashrc 或 cron 环境
export QING_AGENT_MAX_RETRIES=3
```
注意：仅增大超时仍无法完全消除风险——DeepSeek API 在交易时段偶发 >120s 延迟时的后备方案仍是 fallback。

**blast radius 快速检查**：
```bash
# 新版标记：[Qing-Agent ✗ FALLBACK]  旧版标记（兼容）：[qing-agent fallback
for dir in ~/.hermes/cron/output/*/; do
  latest=$(ls -t "$dir"/*.md 2>/dev/null | head -1)
  [ -n "$latest" ] && grep -lE "Qing-Agent . FALLBACK|qing-agent fallback" "$latest" && echo "  $(basename $dir)"
done
```
- 输出为空 → 所有 cron 的 Qing-Agent 正常工作
- 有输出 → 列出的 job ID 全部在走 fallback

**端点验证**：
```bash
# /health 通过 ≠ 管线正常
curl -s http://localhost:8000/health        # 确认进程存活

# 必须测实际工作端点（gunicorn 单 worker 下约 15-30s）
curl -v --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"诊断","session_id":"diag-001","analysis_type":"market"}'
# 正常：返回 JSON 含 final_output
# 异常：timeout / 0 bytes / connection refused
```

**gunicorn 进程检查**：
```bash
pgrep -a -f "gunicorn"
# 应看到：master (PID X) + worker (PID Y)
# 如果只看到一个进程 → 可能还在用旧 uvicorn，需重启
```

**区分**：fallback 消息 vs 正常消息：
| 标记 | 含义 |
|------|------|
| 输出含 `[Qing-Agent ✓]` | Qing-Agent 正常参与 |
| 输出含 `[Qing-Agent ✗ FALLBACK]` | Qing-Agent 离线，LLM 直出 |
| 无任何标记 | 非 agent cron（no_agent=true）或独立路径（如收盘复盘） |

## 微信 iLink 限流与 Cron 偏移

**问题**：多个 cron job 在同一分钟（如 :00、:10、:30）向微信发送消息时，iLink 触发 rate limit，导致部分消息静默丢失。

**日志特征**：
```
Weixin send failed: iLink sendmessage rate limited: ret=-2
```

**解决方案**：高频轮询 job（每5分钟）偏移 1 分钟，避开整点/整5/整10分钟。

```bash
# 旧：:00 :05 :10 :15 :20 :25 :30 :35 :40 :45 :50 :55
# 新：:01 :06 :11 :16 :21 :26 :31 :36 :41 :46 :51 :56
cron schedule: "1-56/5 9-15 * * 1-5"  # 而非 "*/5 9-15 * * 1-5"
```

**冲突检查**：新增或修改 cron schedule 前，列出所有 deliver=weixin 的 job 的分钟数，避免新 job 与已有 job 的分钟数重叠。
