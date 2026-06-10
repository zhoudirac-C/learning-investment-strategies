# Config-Cron 对齐诊断决策树

## 症状 A：微信消息质量明显下降

**典型信号**（2026-06-10 发现）：
- 输出引用的方向已过期（如还在说「燃气轮机/工程机械/创新药」，但 UP 已转向「上游材料/半导体」）
- 引用的关键点位已过期（如还在说「上证跌破4000减仓」，但指数已在4000附近拉锯多日）
- 输出完全没有分析中证全指(000985)，只有上证
- 输出风格缺乏 UP 框架感（干瘪的技术罗列而非「赔率思维」「修复质量推演」）

**根因**：Qing-Agent 服务挂了，cron 走了 LLM fallback 路径——LLM 无法访问 Qdrant/Neo4j claims，只能基于 strategy_pack 的纯文本做分析（而 strategy_pack 的文本可能已过期）。

## 症状 B：微信没收到某条 cron 消息

cron `list` 显示 `last_status: ok` 但没收到。

## 诊断决策树（按优先级）

### Step 0: Qing-Agent 健康检查（新增，必须先执行）

当发现消息质量下降或空输出时，第一步先检查 qing-agent：

```bash
curl -s http://localhost:8000/health
```

- **200 + `{\"status\":\"ok\"}`** → qing-agent 正常，继续 Step 1
- **无响应 / Connection refused** → qing-agent 挂了，这是根因。立即重启：

```bash
cd ~/learning-investment-strategies
# 先清理旧进程
pkill -f 'uvicorn.*qing_investment' 2>/dev/null
sleep 1
# 启动（必须 PYTHONPATH=src）
PYTHONPATH=src .venv/bin/python -m uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
# 验证
sleep 3 && curl -s http://localhost:8000/health
```

**Qing-Agent 挂了的完整影响链**：
```
Qing-Agent 进程停止
  → hermes_stock_monitor_agent.py: call_qing_agent() 失败
    → 走 fallback 路径（line 128-130）
      → stock_monitor.py --agent-context-on-trigger
        → 输出原始文本 context（无 claims 注入）
          → Hermes LLM 用 cron prompt 直接生成消息
            → 没有 Qdrant/Neo4j claims → UP 框架缺失 → 质量下降
```

**注意**：Qing-Agent 正常时，cron prompt 几乎不参与（qing-agent 用自己的 LangGraph + claims）。fallback 时才依赖 cron prompt + strategy_pack 文本。所以：
- **改 cron prompt 对 qing-agent 路径无效**（见 skill 纪律 #27）
- **改 strategy_pack + 重启 qing-agent 才是正解**

### Step 1: 检查输出文件

```bash
cat ~/.hermes/cron/output/<job_id>/<timestamp>.md
```

- **文件存在且 `> 0 字节`** → 分析生成了，但 delivery 失败（跳 Step 1a）
- **文件存在但 `= 0 字节`** → 脚本空输出，跳 Step 2
- **文件不存在** → cron 根本没触发，跳 Step 3

### Step 1a: Delivery 失败

日志关键词：
```
grep '<job_id>' ~/.hermes/logs/agent.log | grep -i 'rate limited\|delivery error'
```

- `iLink sendmessage rate limited` → 微信限流。当前无修复方案，考虑降频或偏移 cron 时间。
  - **整点偏移模式**：将 `*/5` 改为 `1-56/5`（:01, :06, :11, :16, :21, :26, :31, :36, :41, :46, :51, :56），避让整点/整5/整10分碰撞。
  - 注意检查 B站监控 cron（`*/10`）也是碰撞源之一。

### Step 2: 脚本空输出诊断

日志关键词：
```
grep '<job_id>' ~/.hermes/logs/agent.log | grep -i 'script produced no output'
```

看到这条日志 → 脚本的 stdout 为空，cron 跳过了 LLM 调用。

**根因判断**：

| 脚本类型 | 空输出原因 | 修复位置 |
|---------|----------|---------|
| `qing_stock_monitor_agent.py` | `find_agent_analysis_trigger()` 返回 None | `strategy_pack.yaml` 的 `agent_analysis_schedule` |
| `qing_stock_monitor_daily_review.py` | DeepSeek API 流式断连 | 等 API 恢复，或改走 qing-agent |
| `qing_stock_monitor_poll.py` | 无触发条件 | 正常（条件驱动，0 token） |
| `sync_daily_state.py` | 正常静默 | 正常 |

**`qing_stock_monitor_agent.py` 空输出根因链**：
```
cron schedule 分钟数 ≠ strategy_pack agent_analysis_schedule 的 time 字段
  → is_scheduled_agent_analysis_time() 返回 False
    → find_agent_analysis_trigger() 返回 None（无 schedule 匹配 + 无 event 触发）
      → run_tick() 返回 ""（空字符串）
        → hermes_stock_monitor_agent.py 收到空 stdout → return 0
          → cron 日志: "script produced no output" → [SILENT] → 不发送
```

### Step 3: 三方对齐检查表

当 Step 2 确认为 schedule 不匹配时，对比三个数据源：

| 数据源 | 位置 | 作用 |
|--------|------|------|
| **A. Cron 实际触发时间** | `cronjob action=list` → `schedule` 字段 | 实际在几点几分跑 |
| **B. strategy_pack 时间** | `strategy_pack.yaml` → `agent_analysis_schedule[].time` | `find_agent_analysis_trigger()` 检查此值 |
| **C. 源码默认值** | `stock_monitor.py` → `DEFAULT_AGENT_ANALYSIS_SCHEDULE[].time` | strategy_pack 缺失时的 fallback |

**对齐规则**：A = B。如果 B 缺失（strategy_pack 无此条目）→ A 必须 = C。

**批量检查命令**：
```bash
# 从 cron list 提取所有 agent 分析时间
for job_id in <id1> <id2> ...; do
  echo "Cron: $(grep -A1 $job_id ...)"
done
# 对比 strategy_pack.yaml 的 agent_analysis_schedule
grep -A2 'agent_analysis_schedule:' config/stock_monitor/strategy_pack.yaml
# 对比源码 DEFAULT
grep -A3 'DEFAULT_AGENT_ANALYSIS_SCHEDULE' src/qing_investment/stock_monitor.py
```

### Step 4: API 故障诊断

**DeepSeek API 流式断连模式**（2026-06-09 首次观测）：

日志关键词：
```
grep '<job_id>' ~/.hermes/logs/agent.log | grep -i 'Stream stale\|RemoteProtocolError\|peer closed'
```

- `Stream stale for 180s — no chunks received. model=deepseek-v4-pro context=~5,382 tokens` → DeepSeek 网关接受连接（HTTP 200）但不返回任何数据
- `RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read) http_status=200 bytes=0 chunks=0 upstream=[server=openresty]` → 确认：网关层正常，推理层节点挂死
- 同一 API key 的其他请求（如对话 session）可能正常 — 这是**路由问题**，不是 key 限流

**区分关键**：API 故障 vs schedule 不匹配的症状相同（微信没收到），但日志完全相反：
- schedule 不匹配 → `script produced no output, skipping AI call`
- API 故障 → 有 AI call，但 `Stream stale` / `API call failed`（连续 3 次重试 + 每次 180s 超时）

**API 故障时的手动救援**：
- 脚本本身正常运行（`stock_monitor.py --daily-review-context` 有输出）
- 但 Hermes LLM agent 无法完成分析
- 可以手动运行脚本查看原始数据：`.venv/bin/python scripts/stock_monitor.py --daily-review-context --ignore-trading-time`
- 等 API 恢复后 cron 自然恢复

### Step 5: `--daily-review-context` 例外

15:20/15:35 收盘复盘使用独立路径 `stock_monitor.py --daily-review-context`：
- **不经过** `find_agent_analysis_trigger()`
- **不检查** `agent_analysis_schedule`
- 脚本总是输出文本 context，但 LLM 调用（deepseek-v4-pro 直调）可能失败
- 空输出原因通常是 LLM API 故障而非配置不匹配

## 实战案例（2026-06-09）

同日发现 3 个 cron 空输出，根因相同：

| cron 时间 | 问题 | strategy_pack 状态 | 修复 |
|----------|------|-------------------|------|
| 10:00 | 空输出 | **缺失**此条目 | 新增 `morning_confirm` 10:00 |
| 10:30 | 正常运行 | ID 错：`morning_confirm`→应为 `opportunity_scan` | 修正 ID |
| 14:55 | 空输出 | 时间错：`14:50` | → `14:55` |
| 15:20 | API 断连 | 不相关（独立路径） | 改为 15:35 重试 |

## 预防

每次新增/修改 cron job 后，检查三方对齐：
```
Cron schedule MM HH  =  strategy_pack.time  =  DEFAULT.time（如 strategy_pack 缺失）
```
