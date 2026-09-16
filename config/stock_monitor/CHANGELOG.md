# Config 变更日志

## 2026-09-16 — 条件轮询 cron 退役（无 YAML 字段改动）

### 变更
- **删除 cron job**「条件驱动轮询（add_zone/风控）」(job `9ba78acd7635`,
  `*/5 9-11,14-15 * * 1-5`)，`qing_stock_monitor_poll.py` 通道退役（脚本保留，
  加退役注释，可手动单跑）。
- 同期删除：观察池热度计算、B站Cookie提醒、日志清理、旧版B站青枫浦上Q监控
  （后三个为 7/28 起暂停的残留），及「观察池热度计算」cron。

### 对 YAML 的影响：**零**
`reduce_zone` / `risk_zone` / `add_zone` 字段与代码读取点均不变
（`PositionRuleEngine.evaluate()`, rules/__init__.py L218–L281）。
变的只是**触发结算通道**：5 分钟机械提醒 → 30 分钟 agent 分析通道。

**给未来改配置的人**：`risk_zone` 命中仍会产生「风控观察」告警，但只在
agent 通道的 tick 上（每 30 分钟）。若你为某标的配了 zone 后期待"秒级提醒"，
**不会有** —— 见 `README.md`「价格区间的三条触发链」。

### 实测数据（2026-09-16）
| 字段 | positions.yaml 命中数 |
|---|---|
| `risk_zone` | 6 |
| `reduce_zone` | 1（512400.SH） |
| `add_zone` | **0**（加仓区目前只写在 `today_plan`/`note` 自由文本里，无结构化提醒） |

### 验证
- [x] `--agent-json-context` 实跑返回 10 条 alerts（含 zone/买入信号候选）
- [x] 两次脚本语法检查通过（项目内 + `~/.hermes` wrapper）
- [x] `RuleEngine` / `validate_position_price_zones` 导入正常

## 2026-06-29 — 6/28 晚间复盘驱动更新

### 复盘核心结论
- 6月15日-26日为完整短线主升与分歧周期，主升已走完
- 6月26日全A指数破位，市场难度明显抬升
- 算力硬件（光通信/PCB/液冷/存储）短期退潮，需等待企稳信号
- 资金将向产业逻辑扎实且临近中报兑现的环节收敛
- 操作策略：右侧确认为先，不追涨，买阴要求更高

### 变更文件
1. `direction_pool.yaml`
   - `updated_at`: 2026-06-26 → 2026-06-29
   - 所有方向 `pre_condition.market` 追加"全A破位后难度抬升，需缩量企稳+右侧确认，不追涨"
   - `pcb_ai_chain`: `diverging` → `ending`（算力硬件退潮）
   - `memory_nor`: `resuming` → `diverging`（存储短期退潮）
   - 新增方向：
     - `semiconductor_silicon_wafer`：半导体硅片涨价
     - `aidc_power_supply`：AIDC供电与国产算力
     - `breeding_hedge`：养殖对冲配置

2. `stock_pool.yaml`
   - `updated_at`: 2026-06-26 → 2026-06-29
   - 新增标的 5 只：
     - 白云电器 603861 → aidc_power_supply
     - 牧原股份 002714 → breeding_hedge
     - 圣农发展 002299 → breeding_hedge
     - 立昂微 605358 → semiconductor_silicon_wafer
     - 锡业股份 000960 → small_metal_chemical
   - 进攻型方向所有标的 `pre_condition.market_actionable` 设为 `false`
   - 防御/对冲方向保持 `market_actionable: true`

3. `strategy_pack.yaml`
   - `updated_at`: 2026-06-25T23:30 → 2026-06-29T00:00
   - `source_claims` 添加 `knowledge/claims/claim-20260628-001.yaml`
   - `market_framework` 更新为 6/28 复盘定调
   - `direction_priority` 更新为 6/28 优先级
   - `operation_plan` 更新为 6/29 操作计划

### 验证
- [x] `direction_pool.yaml` / `stock_pool.yaml` / `strategy_pack.yaml` 均可正常解析
- [x] `MonitorConfig` 可正常加载
- [x] `_build_direction_state()` 对新标的返回正确方向状态

### 待执行
- [ ] 重启 Qing-Agent 加载新配置
- [ ] 盘中 cron 任务自动运行后确认条件单逻辑正常
