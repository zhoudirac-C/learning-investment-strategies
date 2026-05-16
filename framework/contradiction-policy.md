# 矛盾处理规则

冲突分类：

| 类型 | 含义 |
| --- | --- |
| timeframe-shift | 短期与长期视角不同 |
| cycle-shift | 市场阶段变化导致观点变化 |
| logic-broken | 个股或板块逻辑被证伪 |
| risk-repriced | 宏观、流动性或风险偏好改变估值容忍度 |
| true-conflict | 暂无清晰解释，需要人工 review |

新 claim 与旧 claim 冲突时，不删除旧 claim，必须通过 `contradicts` 或 `supersedes` 连接。
