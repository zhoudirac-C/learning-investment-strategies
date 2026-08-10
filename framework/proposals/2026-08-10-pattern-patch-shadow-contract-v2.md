---
date: 2026-08-10
type: pattern-patch
status: open
source: evals/shadow/attributions/2026-08-10.json
---

# 影子输出契约 v2：情景树 / 验证变量 / 失效条件 / 方向定性

## 分析

UP 复盘的可执行结构——节奏判断（分歧被推迟→明后天补分歧）、A/B 情景树（区分关键在承接而非点位）、明日观察清单（可证伪的验证变量）、方向操作定性（进攻/波段/右侧确认/不接飞刀）——在当前输出契约（`market_stage/directions/used_patterns` 三字段）中没有载体。这不是模型能力问题，是契约层缺环节：模型无从输出，评分也无从检验这类判断。

## 处置建议

1. `SYSTEM_PROMPT` 升 v2：要求输出 `scenarios`（分支+区分关键）、`watch_next`（明日验证变量）、`invalidation`（失效条件），方向条目加 `posture`（趋势/波段/右侧确认/回避）；
2. `parse_result` 扩展解析并向后兼容（老记录缺字段=null）；预测 JSON 记录 `prompt_version`；
3. 阶段/方向结算口径不变（不影响在途 pending_maturity 记录）；
4. 版本分界写入毕业判分报告（被测对象变更的度量一致性纪律，见 2026-08-10 模式治理计划）。
