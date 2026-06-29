# Config 变更日志

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
