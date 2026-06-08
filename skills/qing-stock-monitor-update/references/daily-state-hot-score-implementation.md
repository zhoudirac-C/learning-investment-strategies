# Daily State + Hot Score + Claims→Entry 实现参考

> Phase 3-4 架构改造的实现细节。当需要维护或扩展 daily_state、hot_score、claims_to_entry 模块时使用。
> 文档版本：2026-06-08（基于 config-cron-architecture-review.md v2.0 Phase 3-4 实现）

---

## 模块总览

| 模块 | 文件 | 职责 | 调用时机 |
|------|------|------|---------|
| daily_state | `src/qing_investment/agent/tools/daily_state.py` | 盘中观点连续性状态机 | 每个 cron 节点读写 |
| hot_score | `src/qing_investment/agent/tools/hot_score.py` | 观察池热度分计算 | 每日开盘前 |
| claims_to_entry | `src/qing_investment/agent/tools/claims_to_entry.py` | Claims→Entry Point 桥接 | 新 claims 入库后 |
| cron prompts | `src/qing_investment/agent/prompts/system/cron_*.txt` | 3个差异化节点指令 | 09:30/14:00/15:20 |

---

## daily_state.py

### 数据结构

```json
{
  "date": "2026-06-08",
  "market_stage": {"phase": "...", "detail": "...", "updated_by": "...", "updated_at": "..."},
  "direction_priority": [{"direction": "燃气轮机", "intensity": "🔥🔥🔥", "source_claims": [...], "up_quote": "..."}],
  "position_stance": "空仓等待",
  "active_opportunities": [{"stock": "...", "code": "...", "pattern": "...", "trigger": "...", "status": "未触发", "upside": "...", "downside": "...", "ratio": "3:1"}],
  "intraday_narrative": [{"time": "09:30", "summary": "...", "timestamp": "..."}],
  "version": 1
}
```

### 核心 API

- `load_daily_state()` / `save_daily_state()` — 自动处理日期过期（跨天重建）
- `update_market_stage()` — 更新市场阶段
- `update_direction_priority()` — 更新方向优先级
- `update_position_stance()` — 更新持仓态度
- `add_opportunity()` — 添加/更新活跃机会（code 去重）
- `add_intraday_narrative()` — 追加观点演进
- `get_state_summary()` — 生成 human-readable 摘要供 prompt 注入
- `archive_daily_state()` — 收盘后归档到 `daily_state_archive/`

### 使用示例

```python
from qing_investment.agent.tools.daily_state import load_daily_state, update_market_stage, save_daily_state

state = load_daily_state()
state = update_market_stage(state, "等修复", "4033破位后等企稳", "09:30开盘定调")
save_daily_state(state)
```

---

## hot_score.py

### 6维度评分体系

| 维度 | 权重 | 说明 |
|------|------|------|
| claim_freshness | 25% | claims 时效性（≤3天=10分，≤7天=8分，≤14天=6分） |
| up_mention_recency | 20% | UP 最近提及（≤1天=10分，≤3天=8分，≤7天=6分） |
| priority_base | 15% | P1=10分，P2=7分，P3=4分 |
| technical_setup | 15% | 有 buy_setup(+2)、invalidation(+2)、technical_narrative(+1) |
| sector_momentum | 15% | theme claims 平均强度 |
| linked_claims_count | 10% | ≥5条=10分，≥3条=8分，≥2条=6分，≥1条=4分 |

### 分级标准

- A: ≥8.0（高度关注）
- B: 6.0-8.0（重点关注）
- C: 4.0-6.0（常规观察）
- D: <4.0（低优先级）

### CLI 使用

```bash
# 每日开盘前运行
python scripts/calc_hot_scores.py

# 输出
config/stock_monitor/watchlist_hot_scores.json
```

### 集成到 Agent Context

`stock_monitor.py` 的 `format_agent_analysis_context()` 自动注入热度排行摘要：

```python
from qing_investment.agent.tools.hot_score import format_hot_score_summary
hot_score_summary = format_hot_score_summary(limit=10)
```

---

## claims_to_entry.py

### 流程

1. `scan_claims_for_entries()` — 扫描 Neo4j 最近 N 天的 operation claims
2. `parse_operation_claim()` — 正则提取：股票代码、介入区间、仓位、止损
3. `generate_entry_suggestions()` — 回填股票名称和主题信息
4. `merge_with_existing_entries()` — 与现有 entry_points 合并（避免重复）
5. `save_entry_suggestions()` — 生成待确认 YAML 文件

### 提取规则

- 介入区间：`30.5-31.0`、`30.5附近`、`回踩30.5`、`回调到30.5`
- 仓位：`0.5成`、`1成仓`、`50%仓位`、`半仓`、`全仓`
- 止损：`跌破30且30分钟`、`止损30`、`跌破30`
- 股票代码：6位数字

### 输出格式

```yaml
generated_at: "2026-06-08T21:46:00"
total_suggestions: 3
instructions: "请人工审核以下建议，确认后复制到 strategy_pack.yaml"
suggestions:
  - code: "000534.SZ"
    name: "万泽股份"
    entry_zone: "30.5-31.0"
    position_ratio: "0.5成"
    stop_loss: "跌破30"
    claim_id: "claim-20260604-003"
    claim_statement: "..."
    confidence: "high"
```

### 合并策略

- code 已存在 + status=active → 更新 claim_basis
- code 不存在 → 新增（status=suggested，需人工确认）
- code 存在 + status=triggered/executed → 不覆盖

---

## Cron 节点 Prompt

### 3节点设计

| 时间 | ID | 焦点 | 字数 | Prompt 文件 |
|------|-----|------|------|------------|
| 09:30 | morning_open | 竞价定调+核心假设+方向初判 | 200字 | `cron_opening.txt` |
| 14:00 | midday_check | 假设验证+尾盘预案+机会扫描 | 300字 | `cron_midday.txt` |
| 15:20 | closing_review | 全天复盘+预判准确性+明日假设 | 不限 | `cron_closing.txt` |

### Prompt 注入逻辑

`stock_monitor.py` 的 `format_agent_analysis_context()`：
1. 根据当前时间匹配 schedule row
2. 读取对应 `prompt` 字段的 txt 文件
3. 注入到 context 的 "=== 节点专属指令 ===" 段落

### 共享段（所有节点相同）

- daily_state 当前状态
- 观察池热度排行
- 规则信号
- 实时行情快照

---

## add_zone 触发逻辑

Phase 3 新增于 `stock_monitor.py` 的 `evaluate_position_alerts()`：

```python
add_zone = parse_price_zone(row.get("add_zone"))
if add_zone and add_zone[0] <= latest <= add_zone[1]:
    alerts.append(RuleAlert(
        action="加仓观察",
        severity="opportunity",  # 非 risk
        summary=f"加仓观察：...逻辑没变、赔率变好，考虑加仓。"
    ))
```

与 `reduce_zone`（减仓）和 `risk_zone`（风控）并列，形成完整的双向提醒体系。

---

## 常见维护场景

### 场景1：新增评分维度

修改 `hot_score.py`：
1. 在 `_WEIGHTS` 中添加新维度权重（从现有维度中匀出，总和=1.0）
2. 实现 `_score_<new_dim>()` 函数
3. 在 `calculate_hot_score()` 中调用

### 场景2：调整 cron 节点时间

修改 `stock_monitor.py` 的 `DEFAULT_AGENT_ANALYSIS_SCHEDULE`：
- 改 `time` 字段即可，prompt 文件按 `prompt` 字段自动匹配
- 新增节点：添加 dict + 创建对应 `cron_<name>.txt`

### 场景3：claims 提取规则漏报

修改 `claims_to_entry.py` 的 `_ENTRY_ZONE_PATTERNS` / `_POSITION_RATIO_PATTERNS` / `_STOP_LOSS_PATTERNS`：
- 添加新的正则模式
- 测试：`python src/qing_investment/agent/tools/claims_to_entry.py <claim_file.yaml>`

### 场景4：daily_state 字段扩展

1. 修改 `_init_daily_state()` 添加新字段
2. 添加 `update_<field>()` 函数
3. 修改 `get_state_summary()` 包含新字段的摘要
4. 更新 cron prompt 中 "daily_state 更新" 段落

---

## 与现有系统的集成点

```
┌─────────────────────────────────────────────────────────────┐
│  Cron 09:30/14:00/15:20                                     │
│  └─→ stock_monitor.py::format_agent_analysis_context()     │
│      ├─→ daily_state.load_daily_state() → 注入状态摘要      │
│      ├─→ hot_score.format_hot_score_summary() → 注入热度排行 │
│      ├─→ 读取 cron_*.txt → 注入节点专属指令                 │
│      └─→ 生成完整 prompt → 发送给 LLM                       │
├─────────────────────────────────────────────────────────────┤
│  每日开盘前 (cron 或手动)                                    │
│  └─→ scripts/calc_hot_scores.py                            │
│      └─→ hot_score.calculate_all_hot_scores()              │
│          └─→ 输出 watchlist_hot_scores.json                 │
├─────────────────────────────────────────────────────────────┤
│  新 claims 入库后 (手动或 cron)                              │
│  └─→ claims_to_entry.run_claims_to_entry_bridge()          │
│      └─→ 输出 entry_suggestions/entry_suggestions_*.yaml    │
│          └─→ 人工确认 → 复制到 strategy_pack.entry_points   │
└─────────────────────────────────────────────────────────────┘
```
