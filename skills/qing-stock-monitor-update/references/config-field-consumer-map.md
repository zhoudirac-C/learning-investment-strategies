# Config 字段消费方映射

**原则**：只改系统真正消费的字段。加字段前先确认有代码/工具消费它。

---

## watchlist.yaml

| 字段层级 | 字段 | 消费方 | 消费类型 |
|---------|------|--------|---------|
| `theme` | `id` | — | 仅人类可读标识 |
| | `name` | LLM prompt（上下文展平后） | 展平的 name 被 Agent 看到 |
| | `up_positioning` | LLM prompt | Agent 分析上下文 |
| | `source_docs` | 人类溯源 | 无代码消费，仅人类查阅 |
| | `market_checks` | 人类 | 无代码消费 |
| `theme.stocks[]` | `code` | poll(entry_zone), Agent(context builder), 热度分 | 🔴 核心字段，多个消费方 |
| | `name` | poll, Agent | 同上 |
| | `role` | Agent(context builder), 热度分 | 热度分给 P1/P2 加权 |
| | `segment` | 人类 | 无代码消费 |
| | `priority` | 热度分 | 🔴 核心——决定热度加权、Agent 关注度 |
| | `watch_reason` | LLM prompt | Agent 上下文展平后 |
| | `confirm_with` | 人类/Agent | Agent 可见但不强制消费 |
| | `entry_zone.price_range` | **poll** | 🔴 poll 唯一的价格区间来源 |
| | `entry_zone.current_ref` | 人类 | 无代码消费（仅参考） |
| | `entry_zone.method` | 人类 | 无代码消费 |
| | `entry_zone.confirm_signal` | 人类/Agent | Agent 参考 |
| | `entry_zone.hard_stop` | 人类 | 无代码消费 |
| | `entry_zone.position_ratio` | 人类/Agent | Agent 参考 |
| | `buy_setup` | **废弃** | 不再被 poll 消费，改走 `entry_zone.price_range` |
| | `invalidation_setup` | 人类/Agent | Agent 参考 |
| | `up_mention_status` | 热度分 | 最近提及时间影响新鲜度分 |
| | `lifecycle.stage` | 热度分 | watching/ready/position 影响权重 |
| | `linked_claims[]` | **热度分**、**Agent context builder**、**Neo4j 检索** | 🔴 三处同时消费——热度分通过 claim 新鲜度加权, Agent 通过 claim 注入上下文 |
| | `hot_score` | 热度分排序 | 仅输出，不写入 |

### 结论：真正有用的字段

```
poll 消费:   entry_zone.price_range
热度分消费:  priority, lifecycle, linked_claims, up_mention_status, role
Agent 消费:  展平后所有可见字段 + linked_claims 注入
```

**"加了等于白加"的字段**：`confirm_with`（无代码消费）、`source_docs`（仅人类溯源）、`segment`（仅人类可读）、`method`（仅人类可读）。不删但也不必执着于维护。

**危险字段**：`buy_setup`（已被 entry_zone.price_range 替代，保留旧数据会导致 poll 读取混乱）

---

## strategy_pack.yaml

| 字段 | 消费方 | 消费类型 |
|------|--------|---------|
| `market_framework` | LLM prompt | Agent prompt 注入 |
| `index_rules` | poll | 🔴 poll 计算指数触发 |
| `intraday_schedule` | poll | 🔴 poll 判断是否为交易时段 |
| `agent_analysis_schedule` | stock_monitor --agent-json-context | 🔴 决定何时触发 Agent 分析 |
| `sector_groups` | poll(板块轮动), Agent | 🔴 sector_strength 计算 + Agent 上下文 |
| `sector_rotation_rules` | poll | 🔴 板块轮动信号触发 |
| `entry_points[]` | poll, Agent | 🔴 条件驱动触发 + Agent 上下文 |
| `position_rules` | Agent | Agent 参考 |
| `linked_daily_state` | — | 仅路径引用，无代码消费 |
| `strategy_meta` | — | 仅人类可读 |

---

## positions.yaml

| 字段 | 消费方 | 消费类型 |
|------|--------|---------|
| `accounts[].positions[].code` | poll, Agent | 🔴 |
| `shares` / `cost` | Agent | LLM 参考（N/A 时为空） |
| `reduce_zone` | poll | 🔴 poll 检测减仓触发 |
| `risk_zone` | poll | 🔴 poll 检测风控触发 |
| `add_zone` | poll | 🔴 poll 检测加仓触发 |
| `t_zone` | — | 无代码消费 |
| `entry_decision` | — | 仅人类参考 |
| `trade_log` | — | 仅人类参考 |
| `portfolio_stats` | — | 仅人类参考 |

---

## 设计原则

1. **加字段前先确认消费方**：`grep -rn "新字段名" src/ scripts/ --include="*.py"` 确认有代码读它。没有的话别加——你说服自己"未来会用"的字段，未来也不会用。

2. **装饰性字段 = 维护负担不加值**：`segment`、`method`、`source_docs` 这些人类可读字段保留即可，不需要增加类似的。LLM 不看它们，热度分不读它们，poll 不碰它们。

3. **顶层嵌套结构不被系统消费**：watchlist 的 theme → stocks 两级嵌套在 JSON 序列化时被展平。父 theme 不被任何代码消费——系统只读展平后的 per-stock 字段。不要添加父 theme 或中间层级。

4. **复用现有字段 > 新增字段**：price_range 已有三个结构（entry_zone.price_range / add_zone / reduce_zone），不要为同一语义另起炉灶。如果现有字段语义不符，先改现有字段的消费方代码，再加新字段。
