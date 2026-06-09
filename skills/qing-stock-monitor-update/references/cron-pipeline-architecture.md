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
