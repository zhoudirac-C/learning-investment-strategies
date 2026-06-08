# Claims 审核清单

> 从 2026-06-08 ingestion 中提炼的规则，补充到 claim 审核流程。

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

## 5. "随便验证"=系统性验证，非抽样检查

当用户说"随便验证一下"某事（如"随便验证一下claim字段是否完整"），这不是敷衍请求——用户期望的是**系统性全量验证**。

- **反面案例**：只做单文件抽样检查 → 用户实际期望全部claims字段完整性审计
- **正确做法**：执行完整验证流程（如全部claims的18个必需字段检查），汇报具体数字（"✅ 21/21 claims 字段完整"）
- **规则**："随便"是用户的自谦表达，不代表降低标准

## 6. 元认知工作流请求（Memory + Skills 更新）

当用户要求"Review the conversation above and update two things: Memory + Skills"时，这是**元认知工作流请求**，期望agent在重要session结束后主动反思。

- **执行内容**：
  1. Memory：检查是否有新发现的用户偏好、纠正、个人细节
  2. Skills：检查是否有需要patch的内容（pitfall、workflow改进、反模式）
  3. 汇报：说明更新了哪些memory条目、skill patch内容
- **信号判断**：用户说"update two things"是明确的结构化指令，不是开放式讨论——直接执行，不需要先问"您想更新什么"

## 7. 置顶评论补充的 claim 审核要点

当处理 UP 置顶评论补充时，审核需额外关注：

- **intensity 必须 high**：置顶评论是 UP 复盘后追加的重要补充，不是普通评论
- **related_claims 必须链接主 claim**：补充 claim 必须与同一 raw 的主 claims 建立关联（如 `claim-20260608-004-j` 链接 `claim-20260608-004-a`）
- **interpretation 必须说明补充性质**：明确标注这是"复盘后追加""视频遗漏补充"，与主 claims 的关系（补充/修正/强化）
- **tags 必须含 `置顶评论`**：便于后续检索和分类
- **不要重复提取主 claims 内容**：补充 claim 只包含置顶评论中的新信息，不重复 raw 正文中已有的内容
- **evidence_quote 必须完整**：置顶评论通常很短（1-3句话），应完整引用原文
