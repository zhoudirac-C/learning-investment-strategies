# Claims 审核清单

> 从 2026-06-08 ingestion 中提炼的四条规则，补充到 claim 审核流程。

## 1. 同日期多篇 raw 必须独立阅读

同一日期的连续发布（如 09:03 早盘 → 09:28 盘中动态），后续动态可能对早盘指令做节奏修正（如"先看修复再清仓"），但**早盘原文不一定包含这个修正**。

- **规则**：每篇 raw 的 claims 只从该 raw 原文提取
- **反面案例**（2026-06-08）：早盘写"今日早盘执行清仓"，盘中动态说"我说了先看修复"，Agent 错误推断早盘也说了等修复——实际早盘原文没有这句话
- **正确做法**：跨 raw 的连贯性通过 `related_claims` 链接，不通过回填 statement 实现

## 2. 禁止多主题/多标的合并（claim 原子性）

一条 claim 只能包含一个主题、一个方向、或一只标的。

- **反面案例**：化工+养殖+非银+光伏 4 个行业合为一条 → Qdrant 语义向量被稀释，Agent 无法单独引用
- **反面案例**：金禄电子+天准科技合为一条 → 两只独立标的混在同一 statement
- **纠正**：拆分为独立 claim，每条 subject 是单一实体
- **验证**：审核时检查 subject 是否含「/」「、」「+」等多实体标记

## 3. 不同 claim_type 可以有内容重叠（不要误删）

两条 claims 的 statement 可能存在重叠（如都包含"清仓+纠错信号"），但如果 `claim_type` 不同（如 `operation` vs `methodology`），它们在 Agent 中的消费逻辑完全不同。

- **operation** → Agent 即时操作信号区
- **methodology** → Agent 方法论引用区
- **规则**：只删除 claim_type 相同且内容真正重复的 claim
- **反面案例**：Agent 建议删除 001-a(operation) 因为与 001-i(methodology) 内容重叠 → 用户纠正："不同的 type，可以删吗？" → 结论：不能删
- **审核判断标准**：①是否不同 claim_type？②各自的 interpretation 角度是否不同？若两者都是"是"→保留

## 4. 同日期多 raw 的 interpretation 必须标注时间线位置

当同一日期有多篇 raw（早盘→盘中→午盘），每条 claim 的 `interpretation` 必须明确它在时间线中的角色。

- **规则**：interpretation 说明该 claim 是初始信号/修正/强化，与前后 raw 的关系
- **反面案例**（2026-06-08）：09:03 早盘说"今日早盘执行清仓"，09:28 盘前2分钟追加"今天看修复"。如果 002-a 的 interpretation 不写「盘前2分钟紧急追加的节奏修正」，Agent 检索时会把两个当平行信号，无法理解"清仓 vs 等修复"的递进关系
- **正确做法**：
  1. interpretation 说清时间线位置（"盘前2分钟紧急追加" / "午盘前再强调"）
  2. `related_claims` 链接前后时间点的相关 claim
  3. wiki 中用时间线章节串联（一/二/三）
- **验证**：审核时查同一日期多篇 raw → 确认每条 interpretation 含时间线标注
