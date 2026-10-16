# 提炼方法论对照：gator-method（第三方） vs 本项目 claim / pattern 管线

> 日期：2026-10-16
> 触发：用户问「提炼库是怎么提炼出 50 规则的，我们能否借鉴优化成自己的提取炒股框架的方法论」
> 取证：GitHub API 完整文件树 + 帧文案原文 + 本项目脚本/prompt 实读
> 关联：`sources/third_party/gator-method-README.md`（上游查证结论）、
>      `docs/design/dual-school-architecture.md`（P3 程序化拆解设计）

---

## 〇、结论前置（4 条）

1. **它的工艺不可复现**（黑盒 Agent、无 prompt 落盘、提炼在项目外），所以「借鉴」只能是
   **借方法论点**，不是借实现。
2. **我们其实已经在用它的思路了，而且更工程化**：它做「文章→IF…THEN 规则」，
   我们做「raw→claim（门禁 5 道）+ raw→reasoning-pattern（18 框架）」，
   **我们是两条正交管线、有 Python 门禁强制、有状态机编排 —— 比它透明得多**。
3. **它有 4 个机制值得我们抄**：①阈值硬约束 ②三种 AI 缺陷的假阳性分类
   ③「翻译」的中间表示意识 ④来源强度分级。
4. **我们有 3 个它没有的优势**：①可复现的编排+门禁 ②观点演进（supersedes/contradicts）
   ③双学派冲突并列机制。**不要为了学它而砍掉这些**。

---

## 一、两边管线对照表（事实）

| 维度 | gator-method（第三方） | 本项目 |
|---|---|---|
| **输入** | 711 篇文章 + 79 场直播转写（65.7 万字） | `sources/original/bilibili/` + `sources/raw/财经/` + `sources/original/wechat/` |
| **转写** | mlx-whisper 本地 | 沿用上游，无自有转写 |
| **提炼主体** | **WorkBuddy 大模型 Agent（黑盒）** | **LLM + Python 门禁编排**（`extract_claims_pipeline.py`） |
| **可复现性** | ❌ 无脚本、无 prompt | ✅ 状态机 + 5 道 gate + 提示词在 `next_action()` 内明文 |
| **产物 A** | 55 章 `IF…THEN` 规则 | claim 库（19 必填字段 + stance 等） |
| **产物 B** | — | reasoning-pattern 18 框架（语义路由） |
| **产物 C** | — | `gator_rules.py` 代码化规则（阈值集中管理） |
| **质量门禁** | 仅 `CONTRIBUTING.md` 四条**写作要求**（人审） | **5 道 Python gate 强制**（字段/枚举/代码/原子性/公司名） |
| **强度分级** | `[核心]/[次要]/[单源]/[可计算]` | `intensity` + `confidence` + `stance` |
| **回测** | 有对齐表，**作者自认没验证** | 有回测框架，明确「样本不足不裁决」 |
| **观点演进** | ❌ 无 | ✅ `supersedes` / `contradicts` + discover 关系发现 |
| **多专家冲突** | ❌ 单学派 | ✅ `school-conflicts.yaml` 双列并列 |

**关键判断**：**我们的 claim 管线在工程上是它的超集。** 真正缺的不是管线，是
**规则化那一层**的几条约束。

---

## 二、它值得抄的 4 个机制（逐条给落地方案）

### 机制 1：`IF…THEN + 数字阈值` 的硬约束

**它怎么做**（CONTRIBUTING 四条硬要求第 1 条）：
> 「量能不足」不算规则，「成交额 < X 亿」才算

**它为什么有效**：把「不可检索、不可判断、不可复用」的口语，强制翻译成可计算形式。
作者在视频里明说：「换个说法就找不到了」。

**我们的现状**：claim 有 `statement` + `evidence_quote`，但**没有强制阈值抽取**。
一条 claim「量能不足要谨慎」在库里和「成交额<8000亿要谨慎」长得一样。

**落地方案（建议编号 A1）**：
- claim schema 加**可选**字段 `thresholds: list[str]`，在 `extract_claims_pipeline.py`
  Step 1 prompt 里要求：**凡 statement 含可量化判断，必须把数字阈值抽到 `thresholds`**。
- **不要做成必填** —— 我们的 claim 覆盖方法论/哲学类（如「预案≠预测」），本就没有阈值。
- 参考实现：`gator_rules.py` 已经这么做（阈值集中在文件头常量区）—— 说明架构上可行。

### 机制 2：三种 AI 缺陷的假阳性分类

**它怎么做**（p6 帧原文，作者主动认错）：
> ⚠ AI 可能**曲解原意**，把带限定条件的话绝对化
> ⚠ 可能**过度归纳**，把一次性的说法当长期规则
> ⚠ 有些规则可能是 AI **凭空推断**的，而非作者真实表达

**它为什么有效**：这是**提炼特有的**三种错误模式，比通用的「字段缺失」更贴实际。
尤其第三条「凭空推断」——**是最危险也最难发现的**。

**我们的现状**：`gate_validate_claims.py` 的 5 道门禁全是**结构检查**
（字段/枚举/代码/原子性/公司名）。**没有任何一道检查「这句话真的是 UP 说的吗」**。

**落地方案（建议编号 A2）**：
- Step 1 prompt 增加**「凭空推断」自查项**：
  > 若一条 claim 的 statement 无法在原文中找到逐字对应或等价表述 → 不得写入，
  > 或必须标 `confidence: low` 并在 `interpretation` 注明「推断」。
- 加一道轻量 gate（gate6）：`evidence_quote` 必须在 raw 原文中**至少命中一个
  关键子串**（如 60% 字符重合），否则报错。**这是防「凭空推断」最直接的机械手段。**
- **注意误伤**：UP 常说「这说明…」的推论句，`evidence_quote` 是原句，不会被误杀。

### 机制 3：「翻译」的中间表示意识

**它怎么做**（p3 帧）：
> 原文·口语表达：「量能不足要谨慎」→（翻译）→ 结构化规则：`IF 微盘股跌>=3% AND 跌停家数>30 …`

**它为什么有效**：它**显式承认这是在「翻译」而非「摘抄」** —— 所以对保真度敏感，
所以才要主动认错（机制 2）。

**我们的现状**：claim 有 `statement`（提炼后）+ `evidence_quote`（原文），
**结构上已经是「原文↔提炼」对照** —— 这一点我们比它规范（它的规则章节只有 source_ref）。

**落地方案（建议编号 A3）**：
- **无需改动**。但应在 `qing-learning-claim` skill 里**明确写一句**：
  「claim = 翻译而非摘抄；`evidence_quote` 是保真锚点，不许改写。」
- 这是文档补强，不是功能改动。

### 机制 4：来源强度分级

**它怎么做**：`[核心]`（多篇反复） / `[次要]`（偶有提及） / `[单源]`（仅一处） / `[可计算]`

**它为什么有效**：**用语料出现频次当置信度代理**，比人工拍脑袋可靠。

**我们的现状**：有 `intensity` + `confidence`，但 **`[单源]` 这一档没有显式对应**。
而我们已知 gator 侧存在「单源放宽进入」的章节（43.5/47 章，用户拍板降标）。

**落地方案（建议编号 A4）**：
- 评估在 claim `confidence` 枚举里明确 `single_source` 档，或
- 在 `reasoning-patterns-gator.yaml` 的 pattern 上加 `evidence_strength: 核心|次要|单源`，
  直接从规则章节标题的 `[核心]` 标记带过来（**脚本可自动做，`build_gator_patterns.py` 已解析标签**）。

---

## 三、它可计算化的先例（我们已走得更远）

作者把可计算规则写成 `IF…THEN`，**然后就没有然后了**（一句「没做过回测」带过）。

**我们做了两件事它没做**：
1. **`gator_rules.py`（371 行）** —— 把止跌5信号/情绪冰点/剪刀差/护盘三力度
   **真的写成可执行代码**，阈值集中在文件头常量区（便于校准）
2. **语义 / 代码双路**：pattern 走 embedding 语义路由，rule 走确定性代码
   （设计见 `dual-school-architecture.md` §3.4）

→ **这块我们领先，无需借鉴。**

---

## 四、不建议抄的部分（避免走回头路）

| 它的做法 | 为什么不抄 |
|---|---|
| 黑盒 Agent 一把梭 | 我们已用「LLM + Python 门禁」替代，可复现性高得多 |
| 无中间产物落盘 | 我们有 `temp/claims/<session>/` 全链留痕（step1/2/3） |
| 无观点演进记录 | 我们有 `supersedes`/`contradicts` + discover |
| 单学派输出 | 我们有双学派并列 + 冲突不裁决（用户 10-15 拍板） |
| 「48/50/53/55 章」数字混乱 | 我们 pattern 数从脚本产出，可核对（stats 块） |

---

## 五、可执行建议（编号清单，供拍板）

| # | 动作 | 类型 | 工作量 | 建议 |
|---|---|---|---|---|
| **A1** | claim 加可选 `thresholds` 字段 + Step1 prompt 要求抽阈值 | schema+prompt | 中 | 建议做 |
| **A2** | 加 gate6：`evidence_quote` 须在 raw 原文命中关键子串（防凭空推断） | 脚本 | 中 | **优先做** |
| **A2b** | Step1 prompt 加「凭空推断自查项」（找不到原文→不写或标 low） | prompt | 小 | **优先做** |
| **A3** | `qing-learning-claim` skill 明确「claim=翻译非摘抄」 | 文档 | 小 | 顺手做 |
| **A4** | pattern 加 `evidence_strength`（从 `[核心]` 标记自动带） | 脚本+schema | 小 | 建议做 |
| **A5** | 用上游 `07-每日日报/` 对照校验 we-mp-rss 抓取完整性 | 运维 | 小 | 独立任务 |

**优先级判断**：**A2 + A2b 价值最高** —— 因为它是**唯一一个「我们的门禁完全没覆盖、
而对方明确点名」的漏洞**（凭空推断/曲解原意）。A1/A3/A4 是锦上添花。

---

## 六、风险与不确定性

1. **A2 的 gate6 有误伤风险**：UP 原文常有口语转写错误（同音字），机械子串匹配可能
   因转写噪声误报。**建议阈值放宽（如 50-60% 字符重合）+ 只对 `confidence: high` 强制**。
2. **A1 的 thresholds 可能变成形式主义**：若无下游消费者（如关联到 `gator_rules.py`
   或监控告警），字段会沦为装饰。**加字段前先确认消费者**（符合用户「config 字段需有
   consumer」的一贯要求）。
3. **本对照基于帧文案，非完整方法文档**：p4/p6 是 13-19 秒视频帧的口播量，
   可能有未公开的细节。
4. **不要高估它的「全流程无手写」**：作者自己承认渲了 3 轮才想清楚、
   有 3 章人工判定占位 —— 人工介入量其实不小。

---

## 附：取证清单（可复核）

- 上游文件树：`api.github.com/repos/201901060324/gator-method/git/trees/main?recursive=1`
  → 112 条目，零脚本
- 提炼链路帧：`html-video-studio/demo/frames-gator/p4-pipeline.html`（5 节点 + 技术栈表）
- 翻译定义帧：`.../p3-translate.html`
- 缺陷认错帧：`.../p6-limits.html`
- 回测否证帧：`.../p5-nobacktest.html`
- 本项目管线：`scripts/extract_claims_pipeline.py`（Step1 prompt 在 `next_action()`）
- 本项目门禁：`scripts/gate_validate_claims.py`（gate1-5）
- 本项目规则代码化：`src/qing_investment/monitor/rules/gator_rules.py`（371 行）
- 本项目 pattern 草案：`framework/reasoning-patterns-gator.yaml`（50 pattern）
