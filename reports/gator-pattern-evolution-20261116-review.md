# 鳄鱼规则 241 条原始待办复核汇总（2026-11-16）

> 范围：冻结于 2026-11-15T16:56:14+08:00 的241条原始待办；2条右侧提案已应用，其余239条按20个批次逐条复核。
> 边界：本汇总不直接修改生产规则库或生产state；新规则与状态核销分别形成待审提案。observing不是终态。

## 一、覆盖与最终结果

| 项目 | 数量 |
|---|---:|
| 原始冻结待办 | 241 |
| 已批准并应用的右侧细化 | 2 |
| 本批复核覆盖 | 239 |
| 批次/结果文件 | 20/20 |
| 原文核验通过 | 216 |
| 原文核验未通过（全部保留observing） | 23 |

| 最终处置（按claim计） | 数量 | 规则库动作 |
|---|---:|---|
| reinforce | 32 | 仅补证据，待审 |
| refine | 10 | 语义细化，待审 |
| new_theme | 0 | 窄口径分时命题仍为单源观察，不立新规 |
| irrelevant | 56 | 拟关闭为reviewed-irrelevant，待审 |
| rejected | 8 | 拟关闭为rejected，待审；含7条superseded历史版本 |
| observing | 133 | 非终态，继续留在backlog |

加上已应用的2条右侧细化，241条均有明确去向；当前生产规则版本仍为 `1.4-draft`。

## 二、原始分类纠偏

原239条分类为：{'refine': 14, 'new_theme': 134, 'reinforce': 55, 'irrelevant': 35, 'contradict': 1}。最终分类不照单接受LLM结果，迁移如下：

| 原分类 | 最终分类 | 数量 |
|---|---|---:|
| contradict | observing | 1 |
| irrelevant | irrelevant | 25 |
| irrelevant | observing | 6 |
| irrelevant | reinforce | 3 |
| irrelevant | rejected | 1 |
| new_theme | irrelevant | 24 |
| new_theme | observing | 103 |
| new_theme | refine | 3 |
| new_theme | reinforce | 2 |
| new_theme | rejected | 2 |
| refine | irrelevant | 2 |
| refine | observing | 8 |
| refine | refine | 4 |
| reinforce | irrelevant | 5 |
| reinforce | observing | 15 |
| reinforce | refine | 3 |
| reinforce | reinforce | 27 |
| reinforce | rejected | 5 |

## 三、跨日期与跨批次汇总

- `rebound-chasing-panic-selling`：独立复核发现窄口径“分时强势不单独确认更高周期趋势”只有11-09直接支持，撤回new_theme；11-06归ch10 reinforce，11-09继续单源observing。11-12同类“低位不买、大涨追高、下跌割肉”也归ch10 reinforce，保持处置一致。
- `official-broad-etf-support`：11-02作为ch47 reinforce；11-03作为ch47 refine，补“指数托底≠救助杠杆科技”及分批买入边界，不新增重复章节。
- `high-dividend-elastic-barbell`：虽有两日材料，但与ch04/ch27的仓位和红利底仓边界尚需澄清，且比例是个人示例，继续observing。
- `crowd-behavior-contrarian-exploitation`：缺可观测指标、通知样本和时间窗口，继续observing；不得转成反向跟随大V买卖。
- `survival-first`：跨日重复仍是原则口号，没有仓位、回撤、杠杆或离场条件，继续observing。
- `sharp-drop-bottom-v-u`：4条均为2026-10-22，不满足跨日期门槛，且其中3条存在引文/来源问题，继续observing。

共享字段已做累计合并：

- ch56.trigger 合并3条贡献，最终9项；ch56.thresholds 合并2条贡献，最终8项。
- ch47.description 依序合并宽基顺序非机械化与指数托底/杠杆投机救助边界。

## 四、待审提案与状态核销

- `framework/proposals/20261116-gator-241-review-status.yaml`：197条，包含56条irrelevant、8条rejected、133条observing；不改规则版本。
- `framework/proposals/20261116-gator-241-review-evidence.yaml`：32条reinforce，仅补真实证据。
- `framework/proposals/20261116-gator-241-review-refinements.yaml`：10条refine，含双侧引文和完整set。

三份提案均为 `pending-review`，`approved_by/approved_at` 均为null。本任务没有把“复核241条”当作规则或状态提案的blanket批准。批准后，irrelevant/rejected才可终态关闭；observing仍留backlog；reinforce/refine只有实际写回后才标记applied。

## 五、原文证据异常（23条，全部observing）

这些条目不得进入规则类提案；需先修正claim引文或来源映射，再重核。

| claim_id | source_issue |
|---|---|
| claim-20261104-009 | 指定的 _1 raw 在第 30-34 行仅有“视频转写”和“ASR跳过: 长视频 65 分钟超过 20 分钟阈值，请手动转写”，随后直接进入视频封面；claim.evidence_quote 中的整段引文不存在。 |
| claim-20261104-010 | 指定的 _1 raw 只有标题、ASR 跳过标记和封面链接，没有“积攒股本”“生活支出”“财富自由”或“包租公包租婆”等引文；非 _1 文件的封面 OCR 不能替代该条指定 raw 的引文核验。 |
| claim-20261104-011 | 指定的 _1 raw 明确记录长视频 ASR 跳过，且没有图片 OCR 段；claim.evidence_quote 中的十五六年、九年、上班攒钱及买高股息等话术均未出现。 |
| claim-20261104-012 | 实际raw第30-34行只有转写元信息和“ASR跳过: 长视频65分钟超过20分钟阈值”提示；claim.evidence_quote中的市场叙事、高股息抱团及3%股息率内容均未出现在raw。 |
| claim-20261104-013 | 实际raw仅保留标题、BV号及ASR跳过提示，没有四川成渝、高速路、2028年承诺或十点几股息率的原文。 |
| claim-20261104-014 | 实际raw第34行明确显示长视频ASR跳过，全文相关段落没有格力、地产周期、公司章程或美的对比的转写。 |
| claim-20261104-015 | 实际raw只有ASR跳过提示，无双汇、现金流、扩张阶段或分红比例的原文，claim引文无法核实。 |
| claim-20261104-016 | 实际raw无新奥、燃气、民企、2028年承诺或股价稳健性的转写，只有长视频ASR跳过提示。 |
| claim-20261106-002 | 引文将raw第35行前段“民主党会限制AI的发展……”与后段“AI的下半场一定是应用……”无省略号拼接，中间略过多段内容；“是昨天那个也给大家写的很清楚”位置不对应，且把后段“后面的话就很早就给大家说了”改成“然后”。 |
| claim-20261015-002-b | raw 原句为‘总结：市场底正在形成，时间还不够，往下空间有限，震荡磨底，可以开始试多，右侧信号尚未出现。’；claim 引文以‘……’替代中间整段文字，不是单纯空白、标点或 ASR 格式差异。 |
| claim-20261015-002-f | raw 为‘我喜欢在6月底7月初大盘4100多’及‘科技腰斩再腰斩，其他板块被错杀再错杀的时候做空’；claim 引文删去‘6’和‘7’，并用‘……’替代‘其他板块被错杀再错杀’等文字，不属于单纯空白、标点或 ASR 格式差异。 |
| claim-20261016-004-a | claim.evidence_quote 第3步为“游资进场点火”，raw 第64行实际为“油资进场点火”；去除空白后仍有该汉字差异，且 raw 是微信公众号文本而非 ASR，不能按明显 ASR 格式差异豁免。 |
| claim-20261104-001 | raw 第175行是“未来的加速上涨会越猛”，claim 写成“未来的加速上涨会更猛”；还将 raw 的独立引号段落与下一段合并，存在非纯标点用字差异。 |
| claim-20261104-002 | raw 第185行为“那么会带来更多的增量资金”，claim evidence_quote 为“那么会带来增量资金”，漏掉“更多的”。 |
| claim-20261022-006 | raw 原文为“而且这这周现货还没止跌呢，对吧？现货还没止跌，你期货这边的空头气势正盛的时候就很容易涨。”；claim.evidence_quote 在“对吧？”后少了“现货还没止跌，你”，属于未标省略的文字差异。 |
| claim-20261022-009 | raw在“第一种就是急杀走V了”与“这个牛里面”之间还有“啊，就之前给大家讲过……我给大家聊那个不牛市，通常都是走V的那个急杀后的见底。”等实质内容；claim以“……”替代，不能按连续原文核验。 |
| claim-20261022-010 | raw第36行实际为“那个节点，啊，这种，啊，这种，邦下来”，claim写成“那个节点，啊，这种，啊，邦下来”，漏掉一个“这种，”，不属于空白或标点差异。 |
| claim-20261022-011 | raw第37行先出现“这是这种，就是说急跌后，啊，其实离我们最近的不是二二年……二一、二四年”，随后才出现“就不牛市里面的话，急跌就是这种”；claim颠倒了两段顺序并以省略号拼接。 |
| claim-20261022-013 | raw第56行在“这波反弹以后，对吧？”与“后面就真的是看基本面了”之间还有关于仓位比例、弹性品种和行业机会的多句内容；claim未标省略直接拼接。 |
| claim-20261022-018 | claim.source_path指向sources/raw/财经/2026-10-22-鳄鱼派-视频-急跌后见底信号.md，但该文件完整转写无此引文；相同内容见于sources/raw/财经/2026-10-22-鳄鱼派-视频-基金赎回杀恐慌.md第36行，且claim引文仍以省略号拼接。 |
| claim-20261023-007-a | claim.evidence_quote 将 raw 第66—136行中相隔较远的两处文字拼接，并把‘上证50，因为科技最少……’改为‘上证50。’；中间省略了原因、指数比较和股指期货风险等内容，超出空白、标点或格式差异。 |
| claim-20261026-021 | claim.evidence_quote 写作‘这个可能就针于’，raw 第34行实际为‘这个可能就针对于’；缺少‘对’字，不属于空白、标点或明显 ASR 格式差异。 |
| claim-20261027-016 | claim.evidence_quote 将“不见得有这波强”与“你可以做”直接相连；raw 两句之间还有“对吧？这么讲大家就很明白了。”，不属于空白、标点或单纯 ASR 格式差异。 |

## 六、逐条核销清单（241条）

批次原始结果保留在 `temp/gator-review-20261115T165443/results/`；下表的最终处置已包含汇总层纠偏。

| claim_id | 日期 | 原分类 | 最终处置 | 原文核验 | 批次/既有提案 |
|---|---|---|---|---|---|
| claim-20261015-002-a | 2026-10-15 | reinforce | reinforce | 通过 | batch-005 |
| claim-20261015-002-b | 2026-10-15 | refine | observing | 未通过 | batch-005 |
| claim-20261015-002-c | 2026-10-15 | new_theme | observing | 通过 | batch-005 |
| claim-20261015-002-d | 2026-10-15 | new_theme | irrelevant | 通过 | batch-005 |
| claim-20261015-002-e | 2026-10-15 | new_theme | observing | 通过 | batch-005 |
| claim-20261015-002-f | 2026-10-15 | new_theme | observing | 未通过 | batch-005 |
| claim-20261015-002-g | 2026-10-15 | refine | observing | 通过 | batch-005 |
| claim-20261015-002-h | 2026-10-15 | reinforce | reinforce | 通过 | batch-005 |
| claim-20261015-002-i | 2026-10-15 | reinforce | reinforce | 通过 | batch-005 |
| claim-20261015-002-j | 2026-10-15 | new_theme | observing | 通过 | batch-005 |
| claim-20261015-002-k | 2026-10-15 | new_theme | observing | 通过 | batch-006 |
| claim-20261016-004-a | 2026-10-16 | reinforce | observing | 未通过 | batch-006 |
| claim-20261016-004-b | 2026-10-16 | reinforce | reinforce | 通过 | batch-006 |
| claim-20261016-004-c | 2026-10-16 | new_theme | observing | 通过 | batch-006 |
| claim-20261016-004-e | 2026-10-16 | reinforce | refine | 通过 | batch-006 |
| claim-20261016-004-f | 2026-10-16 | reinforce | observing | 通过 | batch-006 |
| claim-20261016-004-g | 2026-10-16 | new_theme | observing | 通过 | batch-006 |
| claim-20261016-005-a | 2026-10-16 | new_theme | irrelevant | 通过 | batch-006 |
| claim-20261016-005-b | 2026-10-16 | irrelevant | irrelevant | 通过 | batch-006 |
| claim-20261016-005-c | 2026-10-16 | refine | observing | 通过 | batch-006 |
| claim-20261016-005-d | 2026-10-16 | new_theme | observing | 通过 | batch-006 |
| claim-20261019-003-a | 2026-10-19 | reinforce | reinforce | 通过 | batch-007 |
| claim-20261019-003-b | 2026-10-19 | new_theme | reinforce | 通过 | batch-007 |
| claim-20261019-003-c | 2026-10-19 | reinforce | reinforce | 通过 | batch-007 |
| claim-20261019-003-d | 2026-10-19 | refine | irrelevant | 通过 | batch-007 |
| claim-20261019-003-e | 2026-10-19 | reinforce | irrelevant | 通过 | batch-007 |
| claim-20261019-003-f | 2026-10-19 | reinforce | reinforce | 通过 | batch-007 |
| claim-20261019-003-g | 2026-10-19 | refine | refine | 通过 | batch-007 |
| claim-20261019-003-h | 2026-10-19 | new_theme | observing | 通过 | batch-007 |
| claim-20261019-003-i | 2026-10-19 | reinforce | reinforce | 通过 | batch-007 |
| claim-20261019-003-j | 2026-10-19 | reinforce | reinforce | 通过 | batch-007 |
| claim-20261019-004-a | 2026-10-19 | new_theme | observing | 通过 | batch-006 |
| claim-20261019-004-b | 2026-10-19 | new_theme | observing | 通过 | batch-007 |
| claim-20261019-004-c | 2026-10-19 | new_theme | observing | 通过 | batch-007 |
| claim-20261020-001 | 2026-10-20 | new_theme | observing | 通过 | batch-014 |
| claim-20261020-002 | 2026-10-20 | new_theme | observing | 通过 | batch-014 |
| claim-20261020-003 | 2026-10-20 | reinforce | reinforce | 通过 | batch-014 |
| claim-20261020-004 | 2026-10-20 | new_theme | observing | 通过 | batch-014 |
| claim-20261020-004-a | 2026-10-20 | refine | refine | 通过 | batch-001 |
| claim-20261020-005 | 2026-10-20 | new_theme | observing | 通过 | batch-014 |
| claim-20261020-005-a | 2026-10-20 | new_theme | irrelevant | 通过 | batch-001 |
| claim-20261020-005-b | 2026-10-20 | new_theme | irrelevant | 通过 | batch-001 |
| claim-20261020-005-c | 2026-10-20 | reinforce | observing | 通过 | batch-001 |
| claim-20261020-005-d | 2026-10-20 | refine | refine | 通过 | batch-001 |
| claim-20261020-005-e | 2026-10-20 | reinforce | refine | 通过 | batch-001 |
| claim-20261020-005-f | 2026-10-20 | new_theme | refine | 通过 | batch-001 |
| claim-20261020-005-g | 2026-10-20 | refine | irrelevant | 通过 | batch-001 |
| claim-20261020-005-h | 2026-10-20 | new_theme | refine | 通过 | batch-001 |
| claim-20261020-005-i | 2026-10-20 | reinforce | reinforce | 通过 | batch-001 |
| claim-20261020-005-j | 2026-10-20 | refine | refine | 通过 | batch-001 |
| claim-20261020-005-k | 2026-10-20 | new_theme | observing | 通过 | batch-001 |
| claim-20261020-006-a | 2026-10-20 | reinforce | reinforce | 通过 | batch-008 |
| claim-20261020-006-b | 2026-10-20 | irrelevant | irrelevant | 通过 | batch-008 |
| claim-20261020-006-c | 2026-10-20 | new_theme | irrelevant | 通过 | batch-008 |
| claim-20261020-006-d | 2026-10-20 | reinforce | reinforce | 通过 | batch-008 |
| claim-20261020-006-e | 2026-10-20 | reinforce | reinforce | 通过 | batch-008 |
| claim-20261020-007-a | 2026-10-20 | reinforce | rejected | 通过 | batch-008 |
| claim-20261020-007-b | 2026-10-20 | new_theme | rejected | 通过 | batch-008 |
| claim-20261020-007-c | 2026-10-20 | reinforce | reinforce | 通过 | batch-008 |
| claim-20261020-007-d | 2026-10-20 | new_theme | observing | 通过 | batch-008 |
| claim-20261020-007-e | 2026-10-20 | new_theme | observing | 通过 | batch-008 |
| claim-20261020-007-f | 2026-10-20 | reinforce | observing | 通过 | batch-008 |
| claim-20261020-008 | 2026-10-20 | irrelevant | irrelevant | 通过 | batch-015 |
| claim-20261020-009 | 2026-10-20 | new_theme | observing | 通过 | batch-015 |
| claim-20261020-010 | 2026-10-20 | reinforce | reinforce | 通过 | batch-015 |
| claim-20261020-011 | 2026-10-20 | irrelevant | observing | 通过 | batch-015 |
| claim-20261020-012 | 2026-10-20 | new_theme | observing | 通过 | batch-015 |
| claim-20261020-013 | 2026-10-20 | irrelevant | irrelevant | 通过 | batch-015 |
| claim-20261021-008-b | 2026-10-21 | new_theme | observing | 通过 | batch-009 |
| claim-20261021-009-a | 2026-10-21 | new_theme | observing | 通过 | batch-008 |
| claim-20261021-009-b | 2026-10-21 | reinforce | observing | 通过 | batch-009 |
| claim-20261021-009-c | 2026-10-21 | irrelevant | irrelevant | 通过 | batch-009 |
| claim-20261022-001 | 2026-10-22 | new_theme | observing | 通过 | batch-015 |
| claim-20261022-002 | 2026-10-22 | new_theme | observing | 通过 | batch-015 |
| claim-20261022-003 | 2026-10-22 | new_theme | observing | 通过 | batch-015 |
| claim-20261022-004 | 2026-10-22 | irrelevant | irrelevant | 通过 | batch-015 |
| claim-20261022-004-a | 2026-10-22 | reinforce | rejected | 通过 | batch-002 |
| claim-20261022-004-b | 2026-10-22 | new_theme | observing | 通过 | batch-002 |
| claim-20261022-004-c | 2026-10-22 | new_theme | observing | 通过 | batch-002 |
| claim-20261022-004-d | 2026-10-22 | new_theme | observing | 通过 | batch-002 |
| claim-20261022-004-e | 2026-10-22 | reinforce | refine | 通过 | batch-002 |
| claim-20261022-004-f | 2026-10-22 | reinforce | observing | 通过 | batch-002 |
| claim-20261022-004-g | 2026-10-22 | reinforce | rejected | 通过 | batch-002 |
| claim-20261022-005-a | 2026-10-22 | reinforce | reinforce | 通过 | batch-009 |
| claim-20261022-005-b | 2026-10-22 | reinforce | reinforce | 通过 | batch-009 |
| claim-20261022-005-c | 2026-10-22 | new_theme | observing | 通过 | batch-009 |
| claim-20261022-005-d | 2026-10-22 | reinforce | irrelevant | 通过 | batch-009 |
| claim-20261022-005-e | 2026-10-22 | irrelevant | rejected | 通过 | batch-009 |
| claim-20261022-005-f | 2026-10-22 | reinforce | irrelevant | 通过 | batch-009 |
| claim-20261022-006 | 2026-10-22 | new_theme | observing | 未通过 | batch-015 |
| claim-20261022-006-a | 2026-10-22 | reinforce | rejected | 通过 | batch-009 |
| claim-20261022-006-b | 2026-10-22 | new_theme | observing | 通过 | batch-009 |
| claim-20261022-006-c | 2026-10-22 | new_theme | rejected | 通过 | batch-009 |
| claim-20261022-006-d | 2026-10-22 | new_theme | irrelevant | 通过 | batch-010 |
| claim-20261022-006-e | 2026-10-22 | new_theme | irrelevant | 通过 | batch-010 |
| claim-20261022-007 | 2026-10-22 | new_theme | irrelevant | 通过 | batch-015 |
| claim-20261022-008 | 2026-10-22 | irrelevant | irrelevant | 通过 | batch-016 |
| claim-20261022-009 | 2026-10-22 | new_theme | observing | 未通过 | batch-016 |
| claim-20261022-010 | 2026-10-22 | new_theme | observing | 未通过 | batch-016 |
| claim-20261022-011 | 2026-10-22 | new_theme | observing | 未通过 | batch-016 |
| claim-20261022-012 | 2026-10-22 | reinforce | irrelevant | 通过 | batch-016 |
| claim-20261022-013 | 2026-10-22 | reinforce | observing | 未通过 | batch-016 |
| claim-20261022-014 | 2026-10-22 | reinforce | reinforce | 通过 | batch-016 |
| claim-20261022-015 | 2026-10-22 | new_theme | irrelevant | 通过 | batch-016 |
| claim-20261022-016 | 2026-10-22 | irrelevant | irrelevant | 通过 | batch-016 |
| claim-20261022-017 | 2026-10-22 | new_theme | observing | 通过 | batch-016 |
| claim-20261022-018 | 2026-10-22 | reinforce | observing | 未通过 | batch-016 |
| claim-20261023-006-a | 2026-10-23 | new_theme | observing | 通过 | batch-016 |
| claim-20261023-007-a | 2026-10-23 | reinforce | observing | 未通过 | batch-017 |
| claim-20261023-008-a | 2026-10-23 | new_theme | observing | 通过 | batch-017 |
| claim-20261023-009-a | 2026-10-23 | irrelevant | irrelevant | 通过 | batch-017 |
| claim-20261023-010-a | 2026-10-23 | new_theme | observing | 通过 | batch-017 |
| claim-20261026-016 | 2026-10-26 | new_theme | observing | 通过 | batch-017 |
| claim-20261026-017 | 2026-10-26 | new_theme | observing | 通过 | batch-017 |
| claim-20261026-018 | 2026-10-26 | irrelevant | irrelevant | 通过 | batch-017 |
| claim-20261026-019 | 2026-10-26 | refine | refine（已应用） | 已核 | 20261115-gator-right-side-scope |
| claim-20261026-020 | 2026-10-26 | new_theme | observing | 通过 | batch-017 |
| claim-20261026-021 | 2026-10-26 | new_theme | observing | 未通过 | batch-017 |
| claim-20261026-022 | 2026-10-26 | new_theme | observing | 通过 | batch-017 |
| claim-20261026-023 | 2026-10-26 | new_theme | observing | 通过 | batch-017 |
| claim-20261026-024 | 2026-10-26 | refine | observing | 通过 | batch-017 |
| claim-20261027-014 | 2026-10-27 | new_theme | observing | 通过 | batch-018 |
| claim-20261027-015 | 2026-10-27 | irrelevant | irrelevant | 通过 | batch-018 |
| claim-20261027-016 | 2026-10-27 | new_theme | observing | 未通过 | batch-018 |
| claim-20261027-017 | 2026-10-27 | reinforce | reinforce | 通过 | batch-019 |
| claim-20261027-018 | 2026-10-27 | new_theme | observing | 通过 | batch-019 |
| claim-20261027-019 | 2026-10-27 | new_theme | observing | 通过 | batch-019 |
| claim-20261027-020 | 2026-10-27 | new_theme | observing | 通过 | batch-019 |
| claim-20261027-021 | 2026-10-27 | new_theme | observing | 通过 | batch-019 |
| claim-20261027-022 | 2026-10-27 | new_theme | observing | 通过 | batch-019 |
| claim-20261027-023 | 2026-10-27 | reinforce | reinforce | 通过 | batch-019 |
| claim-20261027-024 | 2026-10-27 | new_theme | observing | 通过 | batch-018 |
| claim-20261027-025 | 2026-10-27 | refine | observing | 通过 | batch-018 |
| claim-20261027-026 | 2026-10-27 | reinforce | observing | 通过 | batch-018 |
| claim-20261027-027 | 2026-10-27 | irrelevant | reinforce | 通过 | batch-018 |
| claim-20261027-028 | 2026-10-27 | new_theme | observing | 通过 | batch-018 |
| claim-20261027-029 | 2026-10-27 | new_theme | observing | 通过 | batch-018 |
| claim-20261027-030 | 2026-10-27 | new_theme | observing | 通过 | batch-018 |
| claim-20261027-031 | 2026-10-27 | new_theme | irrelevant | 通过 | batch-018 |
| claim-20261027-032 | 2026-10-27 | reinforce | irrelevant | 通过 | batch-018 |
| claim-20261028-001 | 2026-10-28 | irrelevant | irrelevant | 通过 | batch-019 |
| claim-20261028-002 | 2026-10-28 | new_theme | irrelevant | 通过 | batch-019 |
| claim-20261028-003 | 2026-10-28 | new_theme | observing | 通过 | batch-019 |
| claim-20261029-027 | 2026-10-29 | new_theme | irrelevant | 通过 | batch-019 |
| claim-20261029-028 | 2026-10-29 | new_theme | observing | 通过 | batch-019 |
| claim-20261102-001 | 2026-11-02 | irrelevant | irrelevant | 通过 | batch-020 |
| claim-20261102-002 | 2026-11-02 | reinforce | observing | 通过 | batch-020 |
| claim-20261102-003 | 2026-11-02 | irrelevant | irrelevant | 通过 | batch-020 |
| claim-20261102-004 | 2026-11-02 | new_theme | observing | 通过 | batch-020 |
| claim-20261102-005 | 2026-11-02 | new_theme | reinforce | 通过 | batch-020 |
| claim-20261102-006 | 2026-11-02 | reinforce | observing | 通过 | batch-020 |
| claim-20261103-001 | 2026-11-03 | new_theme | refine | 通过 | batch-020 |
| claim-20261103-002 | 2026-11-03 | reinforce | reinforce | 通过 | batch-020 |
| claim-20261103-003 | 2026-11-03 | new_theme | observing | 通过 | batch-020 |
| claim-20261103-004 | 2026-11-03 | new_theme | observing | 通过 | batch-020 |
| claim-20261103-005 | 2026-11-03 | new_theme | irrelevant | 通过 | batch-020 |
| claim-20261104-001 | 2026-11-04 | irrelevant | observing | 未通过 | batch-010 |
| claim-20261104-002 | 2026-11-04 | contradict | observing | 未通过 | batch-010 |
| claim-20261104-003 | 2026-11-04 | refine | observing | 通过 | batch-010 |
| claim-20261104-004 | 2026-11-04 | reinforce | rejected | 通过 | batch-010 |
| claim-20261104-005 | 2026-11-04 | new_theme | observing | 通过 | batch-010 |
| claim-20261104-006 | 2026-11-04 | new_theme | observing | 通过 | batch-010 |
| claim-20261104-007 | 2026-11-04 | new_theme | observing | 通过 | batch-002 |
| claim-20261104-008 | 2026-11-04 | new_theme | observing | 通过 | batch-002 |
| claim-20261104-009 | 2026-11-04 | new_theme | observing | 未通过 | batch-002 |
| claim-20261104-010 | 2026-11-04 | new_theme | observing | 未通过 | batch-002 |
| claim-20261104-011 | 2026-11-04 | reinforce | observing | 未通过 | batch-002 |
| claim-20261104-012 | 2026-11-04 | refine | observing | 未通过 | batch-003 |
| claim-20261104-013 | 2026-11-04 | new_theme | observing | 未通过 | batch-003 |
| claim-20261104-014 | 2026-11-04 | new_theme | observing | 未通过 | batch-003 |
| claim-20261104-015 | 2026-11-04 | new_theme | observing | 未通过 | batch-003 |
| claim-20261104-016 | 2026-11-04 | irrelevant | observing | 未通过 | batch-003 |
| claim-20261105-001 | 2026-11-05 | new_theme | observing | 通过 | batch-010 |
| claim-20261105-002 | 2026-11-05 | refine | observing | 通过 | batch-010 |
| claim-20261105-003 | 2026-11-05 | new_theme | observing | 通过 | batch-010 |
| claim-20261105-004 | 2026-11-05 | new_theme | observing | 通过 | batch-010 |
| claim-20261105-005 | 2026-11-05 | new_theme | observing | 通过 | batch-011 |
| claim-20261106-001 | 2026-11-06 | new_theme | observing | 通过 | batch-003 |
| claim-20261106-002 | 2026-11-06 | new_theme | observing | 未通过 | batch-003 |
| claim-20261106-003 | 2026-11-06 | new_theme | observing | 通过 | batch-003 |
| claim-20261106-004 | 2026-11-06 | new_theme | observing | 通过 | batch-003 |
| claim-20261106-005 | 2026-11-06 | irrelevant | irrelevant | 通过 | batch-011 |
| claim-20261106-006 | 2026-11-06 | new_theme | irrelevant | 通过 | batch-011 |
| claim-20261106-007 | 2026-11-06 | irrelevant | irrelevant | 通过 | batch-011 |
| claim-20261106-008 | 2026-11-06 | irrelevant | irrelevant | 通过 | batch-011 |
| claim-20261106-009 | 2026-11-06 | new_theme | observing | 通过 | batch-011 |
| claim-20261106-010 | 2026-11-06 | new_theme | observing | 通过 | batch-011 |
| claim-20261106-011 | 2026-11-06 | irrelevant | reinforce | 通过 | batch-011 |
| claim-20261106-012 | 2026-11-06 | irrelevant | irrelevant | 通过 | batch-011 |
| claim-20261109-001 | 2026-11-09 | new_theme | observing | 通过 | batch-011 |
| claim-20261109-002 | 2026-11-09 | irrelevant | observing | 通过 | batch-011 |
| claim-20261109-003 | 2026-11-09 | reinforce | reinforce | 通过 | batch-011 |
| claim-20261109-004 | 2026-11-09 | new_theme | observing | 通过 | batch-012 |
| claim-20261109-005 | 2026-11-09 | new_theme | observing | 通过 | batch-012 |
| claim-20261109-006 | 2026-11-09 | new_theme | observing | 通过 | batch-012 |
| claim-20261109-007 | 2026-11-09 | irrelevant | irrelevant | 通过 | batch-012 |
| claim-20261109-008 | 2026-11-09 | new_theme | irrelevant | 通过 | batch-003 |
| claim-20261109-009 | 2026-11-09 | new_theme | observing | 通过 | batch-003 |
| claim-20261109-010 | 2026-11-09 | new_theme | observing | 通过 | batch-003 |
| claim-20261109-011 | 2026-11-09 | new_theme | observing | 通过 | batch-004 |
| claim-20261109-012 | 2026-11-09 | reinforce | observing | 通过 | batch-004 |
| claim-20261109-013 | 2026-11-09 | new_theme | observing | 通过 | batch-004 |
| claim-20261109-014 | 2026-11-09 | new_theme | observing | 通过 | batch-004 |
| claim-20261109-015 | 2026-11-09 | new_theme | observing | 通过 | batch-004 |
| claim-20261109-016 | 2026-11-09 | reinforce | reinforce | 通过 | batch-004 |
| claim-20261110-001 | 2026-11-10 | new_theme | irrelevant | 通过 | batch-012 |
| claim-20261110-002 | 2026-11-10 | irrelevant | irrelevant | 通过 | batch-012 |
| claim-20261110-003 | 2026-11-10 | reinforce | observing | 通过 | batch-012 |
| claim-20261110-004 | 2026-11-10 | new_theme | irrelevant | 通过 | batch-012 |
| claim-20261110-005 | 2026-11-10 | reinforce | reinforce | 通过 | batch-012 |
| claim-20261110-006 | 2026-11-10 | new_theme | irrelevant | 通过 | batch-012 |
| claim-20261110-007 | 2026-11-10 | new_theme | observing | 通过 | batch-012 |
| claim-20261111-001 | 2026-11-11 | new_theme | observing | 通过 | batch-012 |
| claim-20261111-002 | 2026-11-11 | new_theme | irrelevant | 通过 | batch-013 |
| claim-20261111-003 | 2026-11-11 | irrelevant | irrelevant | 通过 | batch-013 |
| claim-20261111-004 | 2026-11-11 | new_theme | observing | 通过 | batch-013 |
| claim-20261111-005 | 2026-11-11 | new_theme | observing | 通过 | batch-013 |
| claim-20261111-006 | 2026-11-11 | reinforce | reinforce | 通过 | batch-013 |
| claim-20261111-007 | 2026-11-11 | reinforce | reinforce | 通过 | batch-013 |
| claim-20261111-008 | 2026-11-11 | new_theme | observing | 通过 | batch-013 |
| claim-20261111-009 | 2026-11-11 | new_theme | observing | 通过 | batch-013 |
| claim-20261111-010 | 2026-11-11 | irrelevant | irrelevant | 通过 | batch-013 |
| claim-20261111-011 | 2026-11-11 | new_theme | observing | 通过 | batch-004 |
| claim-20261111-012 | 2026-11-11 | new_theme | irrelevant | 通过 | batch-004 |
| claim-20261111-013 | 2026-11-11 | new_theme | observing | 通过 | batch-004 |
| claim-20261111-014 | 2026-11-11 | irrelevant | irrelevant | 通过 | batch-004 |
| claim-20261111-015 | 2026-11-11 | new_theme | observing | 通过 | batch-004 |
| claim-20261111-016 | 2026-11-11 | new_theme | irrelevant | 通过 | batch-004 |
| claim-20261111-017 | 2026-11-11 | irrelevant | irrelevant | 通过 | batch-005 |
| claim-20261111-018 | 2026-11-11 | irrelevant | irrelevant | 通过 | batch-005 |
| claim-20261112-001 | 2026-11-12 | new_theme | irrelevant | 通过 | batch-013 |
| claim-20261112-002 | 2026-11-12 | new_theme | irrelevant | 通过 | batch-013 |
| claim-20261112-003 | 2026-11-12 | new_theme | observing | 通过 | batch-013 |
| claim-20261112-004 | 2026-11-12 | new_theme | observing | 通过 | batch-014 |
| claim-20261112-005 | 2026-11-12 | irrelevant | reinforce | 通过 | batch-014 |
| claim-20261112-006 | 2026-11-12 | new_theme | observing | 通过 | batch-014 |
| claim-20261112-007 | 2026-11-12 | new_theme | irrelevant | 通过 | batch-014 |
| claim-20261112-008 | 2026-11-12 | new_theme | observing | 通过 | batch-014 |
| claim-20261112-009 | 2026-11-12 | irrelevant | observing | 通过 | batch-014 |
| claim-20261113-002 | 2026-11-13 | irrelevant | observing | 通过 | batch-014 |
| claim-20261113-005 | 2026-11-13 | new_theme | refine（已应用） | 已核 | 20261115-gator-right-side-scope |

## 七、验收记录

- 20/20批次、239/239 claim覆盖；无重复或缺失ID。
- 规则类决策均source_verified=true，无低置信度规则动作；7条superseded历史版本均为rejected。
- 独立审查曾指出rebound窄口径实质单源问题；已撤回new_theme并完成复审，无遗留Critical/Major。
- 修正后的三份提案均通过写回器契约校验；共享refine字段累计合并断言通过。
- 相关测试 `tests/test_evolve_gator_patterns.py tests/test_gator_pattern_evolution_apply.py tests/test_pattern_prompt_policy.py`：51 passed；完整测试：2438 passed、4 skipped、5 deselected。
- 修正后临时副本端到端验收：三份提案dry-run前后字节不变；顺序执行后临时规则为1.6-draft、51个pattern；状态为133 observing、56 reviewed-irrelevant、8 rejected、42 applied；backlog仅剩133条observing，unclassified/orphan/unresolved_drift均为0。
- 三份提案在临时副本上重复执行后字节不变；生产规则、生产state、生产提案和既有claims未受测试影响。
- 临时副本验收明细：`temp/gator-review-20261115T165443/e2e-validation.json`。
