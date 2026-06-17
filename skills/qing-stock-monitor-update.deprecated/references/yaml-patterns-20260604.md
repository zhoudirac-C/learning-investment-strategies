# 新增 YAML 配置模式（2026-06-04 会话）

## dedupe_by_type：差异化去重

在 `strategy_pack.yaml` 的 `notification_policy` 中新增：

```yaml
notification_policy:
  suppress_when:
    - 同一信号按类型差异化去重（风控15min/减仓30min/板块轮动30min，见dedupe_by_type）
  dedupe_by_type:
    risk_alert:           # 风控观察类
      dedupe_minutes: 15
      breakthrough_if_price_change_pct: 1.0   # 价格变化>1%时突破去重
    reduce_alert:         # 减仓观察类  
      dedupe_minutes: 30
      breakthrough_if_price_change_pct: 2.0
    sector_rotation:      # 板块轮动类
      dedupe_minutes: 30
      breakthrough_if_price_change_pct: 0     # 不突破去重
```

**已实现**：`stock_monitor.py` 的 `filter_new_alerts()` 已实现读取 `dedupe_by_type` 配置。`record_emitted_alerts()` 同时记录价格以支持突破去重。

### action 到 dedupe_type 的映射规则

```
风控 → risk_alert
减仓 → reduce_alert  
板块/轮动/回流 → sector_rotation
其他 → default
```

## t_zone：做T区间拆分

将持仓的 `reduce_zone` 拆分为做T区和真正减仓区：

```yaml
positions:
  - code: 000066.SZ
    name: 中国长城
    shares: 400
    cost: 18.111
    reduce_zone: 17.50-17.80   # 真正减仓区（成本下方-1.7%~-3.4%）
    t_zone: 17.80-18.15        # 做T区间（接近成本±1.7%）
    risk_zone: 16.80-17.20
```

**设计原则**：
- `t_zone`：窄幅震荡时的操作区间，提醒做T而非减仓
- `reduce_zone`：价格持续走弱时的减仓区间，触发时应比做T区更高紧迫性
- 上沿距成本约-1.7%，符合"接近成本但不触发减仓"的语义

## sector_group 清理三同步

清理 sector_group（如移除已清仓标的）时必须执行三步：

1. **从 `sector_groups.members` 移除**该标的
2. **从 `offensive_group_ids` 移除**该 group（若组变空无活跃成员）
3. **更新 `notification_policy.only_notify_when`** 中的对应提醒条件文字

示例：移除 cpu_self_development 组的万通发展后 →
- 组变空 → 从 offensive_group_ids 移除
- `only_notify_when` 中的 "CPU自研链组内联动恢复或持续分化" → 改为 "ST得润(CPU Socket)脱离ST风险或产业催化超预期" 或类似
