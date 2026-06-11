# Cron 调度优化原则（2026-06-11）

当用户要求「检查定时任务窗口」或「优化调度」时，遵循此流程。

## 前置原则

| 原则 | 做法 | 理由 |
|------|------|------|
| 移动（move） | 非看盘任务移到盘前/盘后 | 释放交易时段调度队列 |
| 偏移（offset） | 分钟位偏移避开 Agent 整点/半整点 | 减少并发冲突 |
| 降频（reduce） | 非关键轮询从5分→15分 | 够用就行 |
| **保留（keep）** | 用户说"很重要"时保留功能，只偏移不删除 | 用户反馈有价值 |

## 交易时段三类任务的优先级

```
P0 — Agent 分析（08:26-14:55 共8个，固定时间）
P1 — poll 条件轮询（每5分钟，检测买入候选+风控）
P2 — B站动态监控（每10分钟，保留但偏移分钟位）
P3 — 健康检查 / Daily State（每15分钟即可）
```

## 调度冲突检查表

当新增/修改 cron job 时，对照 Agent 任务时间检查是否冲突：

| Agent 任务 | 时间 | 避让窗口 |
|-----------|------|---------|
| 集合竞价后 | 09:26 | ±3 分钟 |
| 开盘15分钟确认 | 09:45 | ±2 分钟 |
| 10点确认 | 10:00 | ±5 分钟 |
| 30分钟确认 | 10:30 | ±5 分钟 |
| 上午收盘前 | 11:20 | ±5 分钟 |
| 下午风险窗口 | 13:10 | ±5 分钟 |
| 午盘监控 | 14:00 | ±5 分钟 |
| 尾盘条件单 | 14:52 | ±3 分钟 |

## ⚠️ 双源调度同步（2026-06-11 新增）

Agent 分析时间定义在**两个地方**，必须保持同步：

```
strategy_pack.yaml  → agent_analysis_schedule（代码走 time-slot 匹配用）
Hermes cron job     → schedule 字段（调度器实际触发用）
```

**反面案例（2026-06-11）**：移动尾盘条件单 14:55→14:52，只改了 cron job schedule，忘了改 `strategy_pack.yaml` 的 `agent_analysis_schedule`。虽然 cron 会正确触发，但代码中的 `find_agent_analysis_trigger()` 检查的是 strategy_pack 的时间，可能导致 timing window 不匹配。

**验证命令**：
```bash
# 对比两个来源的时间
echo "=== Cron job 调度 ==="
hermes cron list | grep -E "尾盘|14:"

echo "=== strategy_pack 调度 ==="
grep -A1 "time:" config/stock_monitor/strategy_pack.yaml | grep "14:"
```

**同步流程**：
1. `cronjob(action='update', job_id=..., schedule=...)` — 改 Hermes 调度器
2. patch `strategy_pack.yaml` 中的 `agent_analysis_schedule` 时间 — 改代码逻辑
3. 验证：`grep -A1 "time:" config/stock_monitor/strategy_pack.yaml` 与 cron 列表一致
