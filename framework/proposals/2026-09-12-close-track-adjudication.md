---
date: 2026-09-12
type: adjudication
status: applied
source: [evals/shadow/attributions/2026-09-07.json, evals/shadow/attributions/2026-09-08.json]
adjudicates: [2026-09-07-glossary-patch-note.md, 2026-09-07-pattern-patch-note.md,
  2026-09-07-pattern-patch-t-1.md, 2026-09-08-glossary-patch-note.md,
  2026-09-08-pattern-patch-note.md, 2026-09-08-capability-boundary-note.md]
---

# 合并裁决：09-07/09-08 六份 open 提案（收盘修正轨错因簇）

> 本文档已于 2026-09-12 人审批准并按「实施清单」落地（prompt v19 /
> reasoning-patterns.yaml / up-glossary.md / ai-business-model-falsification.md）。
> 六份原提案保留作溯源，处置以本文为准。

## 背景

W37 盲判周（09-07~09-11）盘前轨 6/6 全对；收盘轨仅有的两次错判是同一模式：
盘前判对「调整」，收盘被单日阳线/未破位触发规则28(a) 翻成「震荡」
（09-07 缩量+隔夜外力映射大阳；09-08 无破位但结构+情绪+资金同步退潮）。
归因一致指向「概念误用 + 步骤缺」，六份 open 提案覆盖同一错因簇。

与 09-09 retracted 组的关系：该组五份提案（含 28(b) 修订、主动降速负面清单、
断板双向解读、震荡vs调整仲裁 checklist）因 09-09 归因被 prediction_rerun
作废而撤回；其议题与 09-08 组高度重叠，本裁决落地后自然覆盖，不单独重开。
若 W38 再发同类错判，再按归因驱动原则重启。

## 裁决明细

| 提案 | 结论 | 落点 |
|---|---|---|
| 09-07-pattern-patch-t-1（冲突裁决+T+1） | merged | 新规则38（收盘重定性冲突裁决+T+1确认），replay.py SYSTEM_PROMPT_V15 |
| 09-07-glossary-patch（28(a)前置+外力映射日） | merged | 28(a) 文本加适用前置（prompt 侧）；「外力映射日」新词条回写 up-glossary.md |
| 09-07-pattern-patch（量能源口对称化） | merged | reasoning-patterns.yaml volume_source_qualify step 2 增补 + 规则38 引用 |
| 09-08-glossary-patch（震荡边界/宽度修复子类/stage-nature联动） | merged | up-glossary.md 新增「震荡（阶段判定口径）」「宽度修复」两词条；stage-nature 一致性校验并入规则38 |
| 09-08-pattern-patch（情绪退潮定量阈值） | applied | reasoning-patterns.yaml sentiment_cycle 增设阈值步骤与 falsification |
| 09-08-capability-boundary（油价分项不可校验） | applied | 规则25 文本修订 + framework/ai-business-model-falsification.md 三条件表注明 |

六份全部收敛为四个落点，无 rejected。merged 而非逐个 applied 的原因：
三份提案同触「收盘改判」环节，分散落笔会在 28(a)、glossary、阶段判定流程
三处重复定义同一约束，合并为规则38 单一入口。

## 要点说明

### 规则38（09-07-t-1 / 09-07-glossary / 09-08-glossary 合并）：收盘重定性冲突裁决+T+1确认

落点：`src/investment_engine/blindtest/replay.py` SYSTEM_PROMPT_V15，追加第 38 条
（盘前/收盘双轨共用同一 SYSTEM_PROMPT，一次修改双轨生效）。条文要点：

1. **触发**：收盘轨拟推翻盘前/昨日 stage 判定（尤其「调整」改判「震荡」）时强制执行。
2. **冲突裁决**：单日修复信号与 ≥2 项在场调整侧证据（宏观利率压制未解除 /
   60min 及以上顶部结构在位 / 量能源头=存量非增量 / 宽基未收复5日线 /
   规则32 防御轮动末端读数）冲突时，禁止即时翻转 stage，降级为「反抽观察」，
   沿用既有词条「缩量反抽（下跌中继）」口径，不新建「反抽」词条。
3. **T+1 确认**：改判须次日验证（回踩不破关键均线 + 量能不缩）方可生效，
   把 watch_next 的「右侧确认」原则固化为阶段改判前置校验项。
4. **stage-nature 一致性自检**（09-08-glossary ③并入）：nature=主动降速或
   自述含调整成分时 market_stage 必须联动为调整，禁止「stage 震荡 +
   nature 主动降速」脱钩输出；与规则14 的 operation↔stage 自检同列。

### 规则28(a) 适用前置（09-07-glossary 并入）

28(a)「破位但收涨=修复尝试中」增加适用前置：**当日量能环比 ≥ 前日**且
**非单一外部链映射驱动**；不满足（缩量大阳 / 涨跌主因可溯源至隔夜外部链）
时信号改标「反抽」，stage 维持原判，收复条件写入 watch_next。
与 V18 规则28(c) 的边界：28(c) 管「无结构确认的情绪走弱日不得升级调整」
（悲观偏置侧），本条管「缩量/外力映射的破位收涨不得升级震荡」（乐观偏置侧），
方向相反、场景互补，实施时保持 `_V18_RULE28_ANCHOR` 锚句不变以维持 V18 拼装。

### volume_source_qualify 对称化（09-07-pattern-patch）

`framework/reasoning-patterns.yaml` volume_source_qualify step 2「定性持续性含义」
增补对称约束：量能源头判定=存量高低切（行业流出对冲流入、成交额平量/缩量）
时，不仅禁止「放量攻击」定性，同等禁止基于单日 K 线的「修复/阶段升级」定性，
stage 维持原判直至增量资金口径出现；falsification 同步补一条。prompt 侧不重复
条文，由规则38 冲突裁决引用该 pattern 名称（V15 第2条已强制逐条对照
core_patterns，yaml 改动自动进入判据）。

### sentiment_cycle 情绪退潮定量阈值（09-08-pattern-patch → applied）

`framework/reasoning-patterns.yaml` sentiment_cycle 退潮信号识别步骤增设阈值：
封板率单日降幅 ≥15pct、炸板 ≥100 家、首板环比降幅 ≥30% 三项满足其二时，
无论跌停家数，情绪状态强制记为「退潮」并从 stage 候选集剔除主升与震荡偏强；
「跌停0家+梯队完整」仅用于区分烈度（瓦解 vs 温和退潮），不得作为否定退潮的
证据；known_failures 追加 2026-09-08 案例。数据全部已在 pack
（emotion.daban 封板率、limit_pool 炸板/首板宽度），无新数据依赖。

### 规则25 油价分项（09-08-capability-boundary → applied）

规则25 宏观三条件文本修订：油价分项在无采集通道期间固定标记「不可校验」
并从计票剔除，按 2/3 条件定案；接入油价数据源后恢复。同步在
`framework/ai-business-model-falsification.md` 三条件表加注同一口径。
复盘已确认该缺口非 09-08 错因主通路（利率条件独立失效覆盖），属口径洁净化。

### glossary 回写（09-07-glossary / 09-08-glossary → merged）

`framework/up-glossary.md` 新增「盲判归因增补（2026年9月12日）」一节：

- **外力映射日**：涨跌主因可溯源至隔夜外部链（费半/存储链/KOSPI 等）时，
  单日 K 线仅作观察项、不参与阶段重定性；阶段改判走规则38 的 T+1 确认。
- **震荡（阶段判定口径）**：要求顶部结构已消解且量能宽度同步企稳；
  顶部结构生效期 + 存量高低切 + 防御补涨独强组合归「调整（防御末端）」。
- **宽度修复**拆子类：「增量普涨修复」与「防御补涨修复」；后者对齐
  煤炭/石油率先转跌的防御穷尽逻辑（规则32），禁止作为震荡承接证据。

### prompt 同步检查（AGENTS.md 要求）

本次改动不涉及大盘分析输出格式（11 项框架与 cycle_state 字段不变），
`market_analysis_framework.txt` 无需同步；若实施中动了输出 JSON 字段，
须回头检查该文件与 `market_analyst.txt`。

## 实施清单（批准后执行）

1. `replay.py`：V15 追加规则38 + 修订 28(a)/25 文本；保护 V18 锚句；
   检查 `validate_result` 关键词校验是否需要登记新锚点（如「反抽观察」）。
2. `reasoning-patterns.yaml`：volume_source_qualify step 2 增补 +
   sentiment_cycle 阈值步骤/falsification/known_failures；
   改后跑 `validate_patterns_file` 整文件校验。
3. `up-glossary.md`：新增 9月12日增补节三词条。
4. `ai-business-model-falsification.md`：三条件表油价行注「暂不可校验」。
5. 六份原提案 frontmatter 改标（4 份 merged + 2 份 applied，注明并入本文档）。
6. 验证：`pytest tests/investment_engine/`（现有断言含规则37 文本，防误伤）；
   用 09-07、09-08 两日 pack 跑 blindtest replay 回归，确认收盘轨不再把
   「调整」翻成「震荡」，且 09-04/09-09/09-11 三个原本正确的日子不改判。

## 不在本裁决范围

- `2026-09-09-data-channel-note.md`（open）：分时微观结构数据缺口登记，
  无采集通道，保留 open 待数据源。
- `20260909-pattern-nomination-price-increase-domestication-inverse.yaml`
  （pending-review）：窗口 14 天、单阶段单点证据，未达提名门槛，继续观察。
- 09-09 retracted 组五份：维持作废，议题已被本裁决覆盖（见「背景」）。
