# Qing-Agent 双入口差异

## 概述

Qing-Agent 提供两个分析入口，架构和数据流完全不同。

## `/analyze/trigger` — Cron 专用入口

**调用方**：`hermes_stock_monitor_agent.py`（Hermes cron）

**数据来源**：调用方提供全部数据（market_snapshot、external_sector_boards、positions、watchlist 等）。自己不拉任何数据。

**工作流**：完整 LangGraph 管线
```
parse_query → retrieve_knowledge → market_analyst → synthesize → style_writer → reviewer
```

**关键限制**：
- `market_analyst` 节点硬检查 `external_sector_boards.available`（`nodes.py:959`）
- 若 `analysis_type` 为 `"market"` 或 `"portfolio"` 且无实时数据 → **拒绝生成分析**，返回 "实时数据不可用"
- 设计意图：cron 在交易时段运行，必须基于实时数据。无数据时硬编分析对交易决策是危险的

**适用场景**：
- 交易时段大盘分析（cron 自动触发）
- 外部已准备好完整的行情+板块+持仓数据
- 需要经过 reviewer 事实核查的正式分析

**接口**：
```python
POST /analyze/trigger
Body: TriggerRequest { trigger, alerts, market_snapshot, positions, watchlist,
       sector_strengths, external_sector_boards, session_id, query }
```

## `/chat` — 用户对话入口

**调用方**：用户手动对话、Hermes 对话 session

**数据来源**：**自己拉取全部数据**：
1. Qdrant 向量检索（qing_knowledge + qing_claims）
2. Neo4j 图遍历（股票代码精准查询 + 关系发现）
3. mem0 记忆检索
4. 实时行情自动获取（指数/个股/板块/K线）
5. 持仓自动匹配（positions.yaml）

**工作流**：简化的直接 LLM 调用（**不经过** LangGraph 管线）
```
用户消息 → 查询类型检测 → 知识库检索 → 实时数据获取 → Prompt 组装 → LLM 直接输出
```

**关键特性**：
- 即使行情数据拉不到（盘后），也**不拒绝分析**——用知识库内容照样产出结果
- 数据拉取失败时静默降级：`external_sector_boards = {"available": False}`
- 不做 reviewer 事实核查

**适用场景**：
- 盘后/非交易时段的配置分析、方向判断
- 基于知识库（claims/wiki）的定性分析
- 不需要实时行情的研究型问题

**接口**：
```python
POST /chat
Body: ChatRequest { message, session_id }
```

## 选择决策树

```
需要分析什么？
├── 交易时段 cron 自动分析（含实时行情）
│   → /analyze/trigger（调用方提供数据）
│
├── 盘后配置审查、知识库分析（不需要实时行情）
│   → /chat（自己拉数据，拉不到就降级）
│
├── 单只股票深度分析（含K线+分时+持仓）
│   → /chat（自动拉取+匹配）
│
└── 快速定性判断（方向/策略基调）
    → /chat
```

## 实战陷阱 #1（2026-06-09）：错用入口

**场景**：盘后用 `/analyze/trigger` 请求 config 审查，传了 `analysis_type: "market"` 但没传 `external_sector_boards`。

**结果**：market_analyst 拒绝："实时数据不可用，拒绝生成分析"。

**正确做法**：应该用 `/chat`，消息里写明要分析的 config 内容和问题。`/chat` 即使拉不到行情数据，照样用知识库产出分析。

**教训**：盘后分析型任务永远用 `/chat`，不要用 `/analyze/trigger`。

---

## 实战陷阱 #2（2026-06-10）：/health 通过但 /analyze/trigger 挂死

**症状**：
- `curl http://localhost:8000/health` → `{"status":"ok"}` ✅ 进程活着
- `curl -X POST http://localhost:8000/analyze/trigger` → 超时，0 bytes 返回 ❌
- 所有 cron job 输出文件含 `[Qing-Agent ✗ FALLBACK]` 标记（旧版：`[qing-agent fallback`）
- 微信消息正常收到，但内容是 Hermes LLM 直接生成的（无 Qing-Agent 知识库检索）

**诊断方法**：
```bash
# 1. 检查 blast radius — 有多少 cron job 在走 fallback
# 新版标记：[Qing-Agent ✗ FALLBACK]  旧版标记：[qing-agent fallback
# 搜索时两个都查
for dir in ~/.hermes/cron/output/*/; do
  latest=$(ls -t "$dir"/*.md 2>/dev/null | head -1)
  [ -n "$latest" ] && grep -lE "Qing-Agent . FALLBACK|qing-agent fallback" "$latest" && echo "  ↳ FALLBACK: $dir"
done

# 2. 直接测试 /analyze/trigger 端点（verbose + 超时）
curl -v --max-time 15 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"诊断测试","session_id":"diag-001","analysis_type":"market"}' 2>&1 | tail -5
# 正常：应返回 JSON（含 final_output）
# 异常：0 bytes received / Operation timed out

# 3. 区分"进程活着"和"管线工作"
# 只查 /health = 只能确认进程没崩
# 必须测 /analyze/trigger = 才能确认 LangGraph 管线正常
```

**根因（已确认，2026-06-10，2026-06-10 二次深化）**：

不是「进程坏了」，是**超时+单worker串行排队**的连锁反应：

1. **LangGraph 管线耗时 30s+**：`/analyze/trigger` 走完整 7 节点管线，含 5 次 LLM 调用（parse_query → market_analyst ∥ stock_analyst → style_writer → reviewer），正常耗 30s
2. **Hermes 脚本硬超时 45s**：`hermes_stock_monitor_agent.py` 中 `QING_AGENT_TIMEOUT` 默认 45s（可通过环境变量调整）
3. **uvicorn 单 worker 串行处理**：无 `--workers` 参数时只有一个 worker，请求严格串行

连锁反应：
```
09:26 cron → POST qing-agent → pipeline 30s，但 DeepSeek API 偶发慢（交易时段）
  → 超过 45s → 脚本超时，走 fallback
  → 但 uvicorn worker 还在后台继续处理（无中断机制！）

09:45 cron → POST → worker 正忙着处理上个请求 → 排队 45s → 又超时 → fallback
10:00 cron → POST → worker 还在忙 → 又超时
...全天 9 个 cron 全部 fallback
```

**验证**：
- 单请求完成 30s ✅
- 5 并发测试：前 4 个 30s 超时，第 5 个才返回 → 证实串行排队
- 同一代码 kill+重启（清空队列）→ 立即恢复
- DeepSeek API 在交易时段出现过 `APIConnectionError`

**修复（三层）**：

| 层级 | 修复 | 效果 |
|------|------|------|
| 治标 | `kill + restart` | 清空队列，立即恢复 |
| 治本 | 设 `QING_AGENT_TIMEOUT=90` | 给管线足够时间完成 |
| 防护 | 脚本加重试逻辑 | 一次超时不放弃，3 次 backoff |

**重启命令**：
```bash
# 1. 杀旧进程
kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null
sleep 2

# 2. 重启动（必须在 repo root，pydantic 从 .env 读 LLM_PROVIDER/DEEPSEEK_API_KEY）
cd ~/learning-investment-strategies
nohup .venv/bin/python -m uvicorn qing_investment.agent.main:app \
  --host 127.0.0.1 --port 8000 > /tmp/qing-agent.log 2>&1 &

# 3. 验证 /analyze/trigger（非仅 /health）
sleep 3
curl -s --max-time 5 http://localhost:8000/health && echo ""
curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"重启验证","session_id":"restart-check","analysis_type":"market"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('RESTART OK' if d.get('final_output') else 'STILL BROKEN')"
```

**Cron 输出标记规范**（2026-06-10 起生效）：
| 输出前缀 | 含义 | 对应 grep |
|----------|------|-----------|
| `[Qing-Agent ✓]` | 成功调用 Qing-Agent | `grep -l "Qing-Agent ✓"` |
| `[Qing-Agent ✗ FALLBACK]` | Qing-Agent 不可达，LLM fallback | `grep -l "Qing-Agent ✗ FALLBACK"` |

标记由 `scripts/hermes_stock_monitor_agent.py` 在 main() 中输出，Qing-Agent 成功时打印 `[Qing-Agent ✓]` 然后输出 final_output，fallback 时打印 `[Qing-Agent ✗ FALLBACK]` 然后输出原始监控上下文。

**对用户的影响**：
- 所有 cron 分析退化为 Hermes LLM 直出（无 Qing-Agent 的 claims 检索/Neo4j 图推理/reviewer 事实核查）
- 可能出现过期方向词、缺少 claims 引用等退化特征
- `/health` 通过造成的假安全感：用户以为 Qing-Agent 在线，实际没参与

**教训**：健康检查必须测实际工作端点，不能只测 `/health`。
