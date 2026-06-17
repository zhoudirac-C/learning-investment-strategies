# 运维陷阱集

> 来源：`qing-stock-monitor-update` skill 的历史踩坑记录（已废弃）
> 保留：仍有效的操作纪律
> 删除：已修复的 bug（仅历史价值）

---

## 陷阱 1: Agent vs UP 矛盾

**案例（2026-06-10）**：万泽跌停，Qing-Agent 建议清仓，UP 10:04 说"直接砍不合适"。

**处理流程**：
1. 时序判断：UP 观点在 Agent 分析之后 → 以 UP 为准
2. 归类：信息不对称 → 补 claims → 重新分析
3. 写入 strategy_pack 时标注来源 claim ID

> 已写入 Agent memory。三类矛盾：信息不对称→补 claims；方法论差异→UP 优先；真正矛盾→标记 true-conflict。

---

## 陷阱 2: 观察池 entry_zone 生命周期管理

当标的股价持续远离原有 entry_zone 时：

| 标的角色 | 原区间状态 | 动作 | 原因 |
|---------|-----------|------|------|
| P1/P2 核心 | 区间失效但逻辑未变 | 移除 entry_zone 或标记 paused | 等回踩重置区间 |
| P3 观察 | 区间失效 | 直接设 `entry_zone: null` | P3 本就不设介入区间 |
| 所有角色 | 连续涨停 | 临时移除候选 | 涨停期间不追高，等分歧日重新算 |

**不要在涨上去后删除标的**。保留但停用 entry_zone，等回踩后恢复。

---

## 陷阱 3: 未经用户确认不修改代码

反面案例：用户说"payload 过大怎么优化"，AI 直接改了 `_agent_context_data()`。

**正确做法**：
1. 先分析问题和方案
2. 展示方案等用户确认
3. 确认后才动手
4. 用户说"等下/别改"→ 立即停止并回滚

---

## 陷阱 4: Cron prompt 空改

改了 cron prompt 但没验证 → 下次执行才发现不生效。

**验证方法**：
```bash
python3 scripts/hermes_stock_monitor_agent.py
# 检查输出是否含新框架关键词
```

---

## 陷阱 5: Hermes cron 默认 120s 脚本超时

Hermes agent 源码硬编码 `cron/scheduler.py` 第 813 行：脚本超时 120 秒。qing-agent API 调用链（行情 15s + HTTP 119s + 开销 39s ≈ 173s）经常超时。

**规避**：脚本内部自行超时控制 + 拆分长任务为多次短调用。

---

## 陷阱 6: Cron prompt 同步遗漏

改了 config 但只更新了 strategy_pack，忘记同步 cron prompt 中的市场阶段描述。结果：LLM 基于旧框架做判断。

**检查清单**：见 `qing-fupan-morning-usage` §Config 变更纪律。
