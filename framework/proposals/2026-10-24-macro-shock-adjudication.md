---
date: 2026-10-24
type: adjudication
status: applied
source: [evals/shadow/attributions/（宏观/外部冲击簇 E：2026-08-17 ~ 2026-10-16 错判日）]
adjudicates: [2026-08-17-data-channel-global-macro-25.md,
  2026-08-19-capability-boundary-note.md, 2026-08-21-capability-boundary-note.md,
  2026-08-25-capability-boundary-note.md, 2026-08-26-capability-boundary-note.md,
  2026-08-27-capability-boundary-note.md, 2026-08-31-data-channel-note.md,
  2026-08-31-capability-boundary-note.md, 2026-09-30-pattern-patch-note.md,
  2026-10-08-capability-boundary-note.md, 2026-10-09-capability-boundary-note.md,
  2026-10-13-capability-boundary-note.md, 2026-10-15-capability-boundary-note.md,
  2026-10-15-capability-boundary-global-macro-sector-intraday.md,
  2026-10-15-pattern-patch-note.md, 2026-10-16-capability-boundary-note.md]
---

# 合并裁决：宏观/外部冲击簇 E 十六份 open 提案（2026-08-17 ~ 2026-10-16）

> 本文档已于 2026-10-24 按「实施清单」落地（prompt v23：规则40 增补「无有效反弹
> 周期在位」声明 / 规则46 外部冲击降级门控（接入 validate_result 机械校验）；
> 盘前轨新增规则42（与盘后规则46 对称）；up-glossary.md 新增 10月24日增补节）。
> 十六份原提案保留作溯源，处置以本文为准。
> 注：任务清单所列 `2026-10-15-capability-global-macro-sector-intraday.md` 实际
> 文件名为 `2026-10-15-capability-boundary-global-macro-sector-intraday.md`，
> adjudicates 以实际文件名为准。

## 背景与共性错因

16 份提案来自宏观/外部冲击相关错判日（08-17/08-19/08-21/08-25/08-26/08-27/
08-31×2/09-30/10-08/10-09/10-13/10-15×3/10-16），剔除各案特异的单点错因
（单点锚定已由 v20 规则40 + 09-18 归因审计项覆盖；恐慌升级判别由规则18 管辖）
后，收敛为四个共性错因：

1. **老批次数据通道诉求已被现体系覆盖**（08-17/08-21/08-25/08-26/08-31×2）：
   global_macro 通道已建成（08-20 提案落地、09-05 增补商品组与 ^IRX、09-05 增补
   美股三指数「源头宽基」），美债三期限/美元指数/美股宽基/费半/存储链/亚太/
   黄金铜全在 pack，规则24/25 挂钩并有 validate_result 规则25 机械校验。
2. **缺失≠不成立**（10-08/10-16）：global_macro 缺失时把「无法证伪外部冲击」
   当作「外生冲击不存在」直接定性「内生瓦解」——两日收敛，且可机械校验
  （pack 缺块是确定性事实），采纳。
3. **「只定价开盘」确定化**（10-09/10-13/10-15-sector-intraday）：外部链条
   不可校验时，仍把规则30 先验（冲击只定价开盘）当作确定结论，未并列次日
   延续备选——三日收敛，采纳；**不推翻规则30**（30 管有外盘数据时的先验
   权重，新规则管数据缺失时的降级义务，互补关系）。
4. **宏观不可判定时操作层不降级**（08-19/08-27/08-31-capability/10-13）：
   宏观三条件不可判定（抓取失败/基数 0）时，仓位上调、新开方向仓、确定化
   纪律动作未受限——四日收敛；其中「当日不升仓」由 08-27/10-13 两独立样本
   提名，采纳。

其中错因 2 两样本、错因 3 三样本、错因 4 四样本（核心机制 2 样本），按项目
证据标准（≥2 独立错判日提名同一机制）合并采纳为 prompt 新规则46（外部冲击
降级门控）；10-15-note 的增量诉求为规则40 口径性增补（单日可落地、同向、
不涉数值阈值，按 merged 处置）；09-30/10-15-pattern 含自拍数值阈值，按
规则15 哲学 + 09-18 先例挂起 pending。

## 裁决明细

| 提案 | 结论 | 一句理由 | 落点 |
|---|---|---|---|
| 08-17-data-channel-global-macro-25 | implemented | global_macro 通道已建成且规则24/25 挂钩，通道诉求闭环；通道建成期间的临时能力边界声明随闭环失效 | resolved_by 回指 global_macro.py + dataset.py + 规则25 |
| 08-19-capability-boundary | merged | 「置信度降级暂定+不把纪律动作确定化」与 10-08/10-16 同机制（4 日收敛），并入规则46(c)；「只覆盖开盘」固定声明已由规则30 边界声明覆盖（09-05 裁决） | v23 规则46(c) |
| 08-21-capability-boundary | implemented | 「不得以单一字段成立外推链条整体」已由 v19 规则25 三态计票口径覆盖（本案自评缺口未致错、仅备案）；铜 HG=F 已闭环，铝/LME/库存周度维持 09-05 登记免费缺口 | resolved_by 回指 v19 规则25 + 09-05 缺口登记 |
| 08-25-capability-boundary | implemented | 道指/纳指已入通道（^DJI/^IXIC）；油价维持 09-12 登记免费缺口；「字段缺失置 N/A、降置信、不参与方向定性推演」即 v19 规则25 计票口径，保持现状写入边界 | resolved_by 回指 global_macro.py + v19 规则25 |
| 08-26-capability-boundary | implemented | 道指/纳指宽基采集已闭环（09-05 增补美股三指数）；「抓取失败当日强制降级+显式标注」并入规则46(b)/(c) 机械校验 | resolved_by 回指 global_macro.py + v23 规则46 |
| 08-27-capability-boundary | merged | 「宏观三条件不可判定→当日不升仓、次日补检」与 10-13 构成 2 独立样本，并入规则46(c)；「映射降为次要证据」已由规则30 边界声明/规则39 覆盖 | v23 规则46(c) |
| 08-31-data-channel | implemented | 铜 HG=F 已闭环（09-05，COMEX 口径）；油价无免费公开通道，维持 09-12 登记缺口，不新增采集 | resolved_by 回指 global_macro.py 商品组 + v19 规则25 |
| 08-31-capability-boundary | merged | 「外部冲击链相关方向提高失效级别/更严盘中确认」与 10-09 同型（2 独立样本），并入规则46(b) 方向层降档 | v23 规则46(b) |
| 09-30-pattern-patch | pending | 系统性风险过滤层含自拍数值阈值（基准跌幅超过-2%），数值阈值类默认挂起（规则15 哲学 + 09-18 先例）且单日样本 | —（重启见下） |
| 10-08-capability-boundary | applied | 「缺失≠不成立：不得据 global_macro 缺失定性内生瓦解」机制样本一（与 10-16 两日收敛），可机械校验 | v23 规则46(a) + validate_result |
| 10-09-capability-boundary | applied | 「冲击持续性可能越过开盘定价，不得预设只影响开盘」三胞胎样本一 | v23 规则46(b) |
| 10-13-capability-boundary | applied | 三胞胎样本二；「当日禁止新增仓位、待次日确认」与 08-27 两样本并入规则46(c) | v23 规则46(b)/(c) |
| 10-15-capability-boundary | merged | 禁单点锚定已由 v20 规则40 + 09-18 归因审计项覆盖；增量「分歧跨窗须声明无有效反弹周期在位」为规则40 同向增补，单日可落地 | v23 规则40 增补句 |
| 10-15-capability-boundary-global-macro-sector-intraday | applied | 三胞胎样本三：缺失/基数0 时禁止「只定价开盘」确定化、须并列恐慌备选；sector_intraday 缺口维持 09-09 登记 | v23 规则46(b) + validate_result |
| 10-15-pattern-patch | pending | 外力扰动硬门槛含数值阈值（宽基同步重挫≥1.5%、下跌/上涨>8:1），数值阈值类挂起；其「量级源头校准」思想已在规则30 第②步（查宽基不查个股） | —（重启见下） |
| 10-16-capability-boundary | applied | 「缺失时标注外部链条无法校验、归因限定内部证据主导/未知」机制样本二（与 10-08 收敛） | v23 规则46(a) |

## 要点说明

### 规则46 外部冲击降级门控（10-08/10-09/10-13/10-15-intraday/10-16 applied；08-19/08-27/08-31-capability merged）

落点：`replay.py` _V23_RULE46 尾部追加 + validate_result 机械校验。三段式：

- (a) **缺失≠不成立**：global_macro 缺失/不可校验时外部链条结论只允许写
  「无法校验」——禁止把缺失当外部冲击不成立而判「内生瓦解」（10-08/10-16），
  同等禁止无任何外盘数据时判「外力扰动」。机械校验：pack 无任何外盘数据
  （global_macro 无实质内容且 overnight_us 无主题）而 nature=「外力扰动」即违规；
  global_macro 缺失而 nature∈{外力扰动, 内生瓦解} 且全文无降级标注
  （无法校验/低置信/备选/暂定/信息差/数据缺失/越过首次定价）即违规。
- (b) **「只定价开盘」不得确定化**：外部链条不可校验时，输出含「只定价开盘」
  确定句而无降级标注即违规（10-09/10-13/10-15 三日收敛）；外部冲击链相关
  方向按此降档、不作为主要催化（08-31-capability merged 入此句）。
- (c) **操作层降级**：宏观三条件不可判定时当日禁止上调仓位/新开方向仓，
  次日补检恢复；阶段结论置信度降级「暂定」（08-19/08-27/10-13）。prompt
  条文层约束，不做机械校验（operation.action 自由文本）。

与规则30 的边界（防规则震荡说明）：规则30 先验（冲击只定价开盘）**在有外盘
数据时维持不变**；规则46 只在数据缺失/不可校验时加降级义务，不修改 30 的
先验方向——10-09 提案「避免预设只影响开盘」的全量推翻诉求未采纳，按缺失
场景增补处置。

### 规则40 增补「无有效反弹周期在位」声明（10-15-note merged）

落点：`_V23_RULE40_NEW` 锚点增补（锚点 assert）——分歧且任一指数 rebound_day
已超 theoretical_window 上限、或底部结构已被破位击穿时，cycle_state.note
必须声明「当前无有效反弹周期在位」，operation 按无周期谨慎档处理，禁止据
单一指数读数推断窗口剩余天数。单点锚定本体已由 v20 规则40 与 09-18 归因
审计项覆盖，本次只补「跨窗/破位失效」的声明句式。

### 老批次 data-channel 关闭为 implemented（5 份）

- 08-17：通道建成 + 规则25 可执行，主诉求闭环。
- 08-21：v19 规则25 计票口径（09-18 增补三态计数/明示有效基数/美联储动向
  不得以美债收益率代理）覆盖「不得以单一字段外推链条整体」；铜 HG=F 闭环；
  铝/LME/库存周度维持 09-05 登记免费缺口（本案自评未致错、仅备案）。
- 08-25：道指/纳指已在通道；油价维持 09-12 登记；其处置建议「保持现状并写入
  方法论边界」与 v19 规则25 + ai-business-model-falsification.md 三条件表一致。
- 08-26：道指/纳指采集闭环（09-05 增补）；「抓取失败降级」机制由规则46(b)/(c)
  吸收（自动获得机械校验）。
- 08-31-data-channel：铜 HG=F 闭环；油价维持 09-12 缺口登记。

### glossary 增补（10月24日节）

`framework/up-glossary.md` 新增「盲判归因增补（2026年10月24日）」节，两词条：

- **外部链条无法校验（降级口径）**：缺失/抓取失败时的归因语言规范
  （缺失≠不成立、无外盘证据不得定外力、只定价开盘不得确定化、当日不加仓）。
- **无有效反弹周期在位**：多指数分歧跨窗/破位失效时的周期声明规范。

### 盘前轨同步

盘前 prompt 新增规则42（与盘后规则46 对称，预判口径：global_macro 今晨落盘
缺失/基数0 时归因写「无法校验」、并列盘中延续备选、动作标「暂定」）。盘前
与盘后共用 validate_result，机械校验自动覆盖双轨。

## 暂缓项与重启条件（2 份 pending，非 rejected）

- **09-30（系统性风险过滤层）**：再出现 ≥1 次「市场基准弱市日高 beta 方向
  补跌致方向 miss」样本即重启（届时 2 样本）；重启时阈值须改相对口径
  （基准放量破位/跌幅居前口径或 watch_next 降档处置），绝对 -2% 阈值不采纳。
  「弱市不选高 beta 方向」的执行层已由规则43(b)/45 部分覆盖，重启重点在
  系统性风险的识别层而非方向层。
- **10-15-pattern（外力扰动硬门槛）**：再积 ≥1 次「外盘行业链大跌但宽基未
  重挫、A 股无差别下跌被误归外力」样本即重启；宽基≥1.5%/8:1 绝对阈值不采纳
  （规则15 哲学），重启时改相对口径（宽基跌幅 vs 行业链跌幅对照 + 下跌家数
  极端宽度读数）。「量级源头校准」方向已由规则30 第②步覆盖。

## 实施清单（已执行）

1. `replay.py`：PROMPT_VERSION v22→v23；`_V23_RULE40_NEW` 锚点增补
   （锚点 assert）；`_V23_RULE46` 追加规则46；SYSTEM_PROMPT 指向 v23。✅
2. `replay.py` validate_result：新增规则46 机械校验（(a) 无外盘数据禁定性
   「外力扰动」+ global_macro 缺失时归因定性须带降级标注；(b) 缺失时
   「只定价开盘」确定句须带降级标注）+ docstring 更新。✅
3. `premarket.py`：新增盘前规则42（与盘后规则46 对称）。✅
4. `up-glossary.md`：新增「盲判归因增补（2026年10月24日）」节两词条。✅
5. `tests/investment_engine/test_validate_result.py`：新增 TestRule46 六组
   （含 10-08/10-15 真实签名）。✅
6. `tests/investment_engine/test_premarket.py`：版本钉 v22→v23；
   `tests/investment_engine/test_daily.py`：版本钉 v21→v23（顺带修复该钉
   自 v22 落地起未同步的存量失败）。✅
7. 十六份原提案 frontmatter 回写（5 applied + 4 merged + 5 implemented +
   2 pending）。✅
8. 验证：`import investment_engine.blindtest.replay` 过锚点 assert；
   `pytest tests/investment_engine/test_status.py test_replay.py
   test_validate_result.py test_premarket.py test_daily.py -q` 181 全绿；
   历史复盘输出机械校验回扫与 LLM 回归见文末两节。✅

## prompt 同步检查（AGENTS.md 要求）

本次改动不涉及输出 JSON 字段与 11 项框架结构，`market_analysis_framework.txt`
与 `market_analyst.txt` 无需同步。

## 历史输出机械校验回扫（已执行）

对 evals/shadow/predictions 全部 69 个盘后交易日输出以 v23 validate_result
回扫（pack 按日重建，65 个有效结果、0 重建失败），规则46 命中 **2 天**：

- **10-15（判错日）**：(a) 型命中——pack 无任何外盘数据（global_macro 与
  overnight_us 均缺）却定性 nature=「外力扰动」，正是 10-15-intraday 提案
  登记的「外力扰动定性缺乏可校验数据支撑」。
- **10-13（判对日）**：同型命中——旧输出 nature=「外力扰动」无外盘证据
  （阶段判定仍对，属归因纪律合法拦截——与方向簇 43/44/45 回扫中判对日
  触发同理）。

其余 63 天零触发（无误伤）。已知边界：10-08 旧输出（「不可校验，故定性内生
瓦解」）未被机械层命中——其全文含「不可校验」字样，通过降级标注关键词门禁；
「不可校验→故定性」的语义误用超出确定性校验能力（与规则18 三信号关键词
校验同款边界），由 prompt 条文约束、LLM 回归验证收敛（见下节：10-08 新输出
已改判主动降速并零违规）。

## LLM 回归记录（已执行，2026-10-24 完成）

通道：sensenova deepseek-v4-flash（Hermes 全局模型解析，同方向簇回归）；对
5 个错判日以 v23 prompt 重跑盘后盲判（临时 pred_dir=/tmp/v23-regression/，
不触碰仓库预测记录；global_macro 落盘止于 09-24，五个回放日 pack 均真实
缺失 global_macro——正是规则46 的目标场景）：

| 错判日 | 原输出 stage/nature | 新输出 stage/nature | 校验 |
|---|---|---|---|
| 10-08 | 调整 / 内生瓦解 | 调整 / 主动降速 | passed |
| 10-09 | 调整 / 主动降速 | 调整 / 外力扰动（带降级表述） | passed |
| 10-13 | 调整 / 外力扰动 | 调整 / 主动降速 | passed |
| 10-15 | 调整 / 外力扰动 | 震荡 / 外力扰动（带降级表述） | passed |
| 10-16 | 调整 / 内生瓦解 | 调整 / 主动降速 | passed |

**结论：**

- **规则46 目标错因全部收敛**：「缺失→定性内生瓦解」两日（10-08/10-16）新
  输出均改判主动降速；「无外盘证据→定性外力扰动」日（10-13，历史回扫实证）
  新输出放弃无证据归因；10-09/10-15 保留外力扰动定性但均带降级表述、
  validation 零违规——模型可学会合规表达。
- **stage 判定无推翻性漂移**：3 个 stage 判对日（10-08/09/13）全部维持原判；
  2 个 stage 判错日（10-15/10-16，真值恐慌）均未达真值——恐慌升级判别属
  规则18 三信号清单域（10-15 提案已登记「三缺一强制升级」步骤缺，非本簇
  错因），留待该簇样本重启时处理，本裁决不扩大战场。
- 五日新输出规则46 机械校验零违规（连同 43/44/45 亦零触发）。

## 不在本裁决范围

- `2026-09-09-data-channel-note.md`（sector_intraday 分时微观结构缺口）：
  维持 09-12 裁决登记，待数据源；10-15-sector-intraday 提案中的
  sector_intraday 缺口部分同此处理，不重复登记。
- 铝/LME/库存周度缺口：维持 09-05 裁决登记免费缺口，无免费公开符号期间
  大宗周期方向按规则36「无显性催化」降级处置。
- 方向簇 D 十九份提案：已由 2026-10-24-direction-adjudication 处置。
- `logs/shadow-status.md` 重生成：按项目惯例统一重生成，本次不动。
