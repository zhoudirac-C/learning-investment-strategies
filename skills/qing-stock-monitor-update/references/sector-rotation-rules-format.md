# sector_rotation_rules 格式规范

> `sector_rotation_rules` 必须与代码解析逻辑匹配。历史版本曾使用 dict 格式，现已统一为 list of dicts。

---

## 当前标准格式（list of dicts）

```yaml
sector_rotation_rules:
  - id: offensive_vs_defensive
    name: 进攻vs防御风格切换
    offensive_group_ids:
      - cpu_self_development
      - upstream_price_increase
      - liquid_cooling
      - cpo_optical
      - compute_rental
      - mlcc_passive
      - chemical_price
      - ai_agent_application
      - compute_power
    defensive_group_ids:
      - medical_observation
      - defensive_stabilizers
      - coal
      - urban_renewal
    min_spread_pct: 1.0
    min_red_ratio_spread: 10
    require_offensive_positive: true
    note: 当前风格切换大概率延续
  - id: avoid_sector_monitor
    name: 规避方向监控
    avoid_group_ids:
      - avoid_semiconductor
      - avoid_consumer
    action: 只观察不介入
    note: 博主明确规避半导体和消费
```

## 关键字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | rule 唯一标识 |
| `name` | string | 人类可读名称 |
| `offensive_group_ids` | list | 引用 `sector_groups` 中定义的 `id` |
| `defensive_group_ids` | list | 引用 `sector_groups` 中定义的 `id` |
| `avoid_group_ids` | list | 规避方向 group 引用 |
| `min_spread_pct` | float | 进攻/防御组均涨幅差阈值（默认 1.0） |
| `min_red_ratio_spread` | int | 红盘率差阈值 |
| `require_offensive_positive` | bool | 防止"跌得少"被误判为"进攻回流" |

## 已废弃格式（不要再用）

```yaml
# ❌ 废弃：dict 格式，无法扩展多 rule
sector_rotation_rules:
  offensive_sectors:
    - AI硬件
    - CPO
    - MLCC
  defensive_sectors:
    - 煤炭
    - 电力
```

## 与 sector_groups 的同步纪律

1. **新增持仓标的**：必须加入对应 `sector_group`，否则不会被纳入板块轮动计算
2. **已清仓标的**：必须从 `sector_group` 中移除，否则会拖累组平均涨幅
3. **group id 引用**：`sector_rotation_rules` 中的 `_group_ids` 必须引用 `sector_groups` 中实际存在的 `id`

## 验证命令

```bash
# 检查 sector_groups 中是否有 rule 引用的 id 不存在
python3 -c "
import yaml
with open('config/stock_monitor/strategy_pack.yaml') as f:
    sp = yaml.safe_load(f)
group_ids = {g['id'] for g in sp.get('sector_groups', [])}
for rule in sp.get('sector_rotation_rules', []):
    for gid in rule.get('offensive_group_ids', []) + rule.get('defensive_group_ids', []) + rule.get('avoid_group_ids', []):
        if gid not in group_ids:
            print(f'ERROR: rule {rule[\"id\"]} references missing group_id: {gid}')
print('Validation done')
"
```
