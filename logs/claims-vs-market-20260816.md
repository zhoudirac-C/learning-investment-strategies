# claims 分桶 vs 市场（2026-08-16）

claims 总数 3719（解析失败文件 0）

## 分桶 × 状态（市场命中率列：claims 库无市场结果回写字段（outcome），命中率不可计算——待 M3 回写机制（市场结果→置信度）落地后本表自动出数。）

| 桶 | n | status 分布 | 市场命中率 |
|---|---|---|---|
| up | 3699 | active:3668, superseded:16, case-only:10, expired:4, contradicted:1 | insufficient_data |
| research | 20 | active:20 | insufficient_data |

## 分桶 × claim_type（UP 画像骨架：哪类观点多）

- **up**（n=3699）: sector-theme:1035, market-cycle:547, technical-knowledge:473, operation:409, stock-view:338, methodology:310, catalyst:197, macro:146
- **research**（n=20）: sector-theme:13, stock-view:3, risk:3, methodology:1

## agent 臂（shadow 盲判到期结算，机械真值 + 5 日超额口径）

- 预测记录 8 天（跳过 0）
- 阶段一致率 100.0%（n=7，与机械真值一致性检查，非预测力证据）
- 方向 5 日超额命中 66.7%（n=3）
- 标的 5 日超额命中 75.0%（n=4）

口径声明：agent 臂 = 盲判轻管线（shadow）；up/research 等桶待回写机制后同表出数。up 桶含缠论课程卡片（sources/chanlun，教材性质，technical-knowledge 类不参与市场命中率）。
