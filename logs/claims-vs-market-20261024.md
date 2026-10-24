# claims 分桶 vs 市场（2026-10-24）

claims 总数 6065（解析失败文件 0）

## 分桶 × 状态（市场命中率列：M3 回写口径，hit/(hit+miss)，5 交易日 forward |收益|≥1% 计 hit/miss）

| 桶 | n | status 分布 | 市场命中率 |
|---|---|---|---|
| up | 6045 | active:5024, superseded:1001, case-only:15, expired:4, contradicted:1 | 42.1%(n=518) |
| research | 20 | active:20 | 样本不足(n=3) |

## 分桶 × claim_type（UP 画像骨架：哪类观点多）

- **up**（n=6045）: sector-theme:1654, market-cycle:1064, methodology:674, operation:648, technical-knowledge:509, stock-view:492, macro:330, catalyst:316
- **research**（n=20）: sector-theme:13, stock-view:3, risk:3, methodology:1

## agent 臂（shadow 盲判到期结算，机械真值 + 5 日超额口径）

- 预测记录 136 天（跳过 0）
- 阶段一致率 75.6%（n=131，与机械真值一致性检查，非预测力证据）
- 方向 5 日超额命中 38.3%（n=180）
- 标的 5 日超额命中 41.7%（n=324）

口径声明：agent 臂 = 盲判轻管线（shadow）；up/research 等桶待回写机制后同表出数。up 桶含缠论课程卡片（sources/chanlun，教材性质，technical-knowledge 类不参与市场命中率）。
