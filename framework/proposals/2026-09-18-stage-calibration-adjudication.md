---
date: 2026-09-18
type: adjudication
status: applied
source: [evals/shadow/attributions/2026-09-17.json, evals/shadow/attributions/2026-09-18.json]
adjudicates: [2026-09-17-pattern-patch-note.md, 2026-09-17-glossary-patch-note.md,
  2026-09-18-capability-boundary-note.md, 2026-09-18-pattern-patch-note.md,
  2026-09-18-pattern-patch-stage.md, 2026-09-18-glossary-patch-note.md]
---

# 合并裁决：09-17/09-18 六份 open 提案（阶段判定双向校准簇）

> 本文档已于 2026-09-18 人审批准并按「实施清单」落地（prompt v19 规则25 计票口径 /
> 盘前规则24 同步 / attribute.py 归因审计项 / up-glossary.md / reasoning-patterns.yaml
> known_failures）。六份原提案保留作溯源，处置以本文为准。

## 背景

W38 盲判周（09-14~09-18）阶段判定 7 对 3 错，两次错判方向相反、互为镜像：

- **09-17 盘前轨**：判「震荡/缩量企稳」，真值「调整」。错因是把单日修复当作排除
  调整的条件——但价格结构前置校验（规则28）、宽度无权单独定企稳、量能相对表述
  （规则15）均已有明文，属**既有规则执行失败**，非规则缺失；增量问题只有宏观
  三条件计票不自洽（1 成立/1 失效/1 不可校验写成「2/3 失效」）。
- **09-18 双轨**：判「调整/主动降速」，真值「震荡」。规则38（09-12 裁决设立，
  用于防止收盘轨把「调整」错翻「震荡」）被扩展为「与任何在场调整侧证据冲突即
  维持原判」的一票否决式锁定——**纠偏过度，矫枉过正**。

核心判断：09-18 组三份提案要求修改的规则38 证据清单，是 6 天前（09-12 裁决）
有意写入的；因单日误判即反向修改，会造成规则来回震荡。两日的共性真缺陷是
**证据资格核验**（陈旧结构信号当有效、宏观利率误入 stage 证据、量能让径混用、
分歧指数单点锚定），而非缺少新的数值门槛。故本裁决只落地纪律性、口径性修正，
数值阈值类提案挂起待样本。

## 裁决明细

| 提案 | 结论 | 落点 |
|---|---|---|
| 09-18-capability-boundary（分歧禁止单点锚定） | applied | attribute.py ATTR_PROMPT 新增审计项 |
| 09-17-pattern-patch（计票自洽+一致性校验） | merged | 规则25 计票口径澄清（replay.py，盘前规则24 同步一句）；一致性自检部分与既有规则11/38③ 重复，不另立 |
| 09-17-glossary-patch（缩量须给基准） | merged | up-glossary.md 新增「缩量/放量（口径约束）」词条；规则15/28 已覆盖执行层，不改 prompt |
| 09-18-pattern-patch-note（右侧信号≥4项触发上调） | pending | 阈值系单日反推（N=1 过拟合），且与规则38「≥2项禁止翻转」对撞；案例记入 sentiment_cycle known_failures 作对照样本，不固化阈值 |
| 09-18-pattern-patch-stage（收敛规则38适用边界） | pending | 涉修改 09-12 裁决有意写入的证据清单，重启条件见下文 |
| 09-18-glossary-patch（宏观利率退出stage证据） | pending | 属框架级重定位，与规则25 宏观三条件设计冲突，单日样本不动 |

## 要点说明

### 规则25 计票口径澄清（09-17-pattern-patch 并入，双轨同步）

落点：`replay.py` `_V19_RULE25_NEW` 追加计票口径——三条件按「成立/失效/不可校验」
三态独立计数并写明各态条数；剔除不可校验项须明示有效基数（「有效2项中失效1项」，
禁止「2/3失效」式混计）；美联储动向须由政策信息核验，不得以美债收益率当日变动
代理。盘前轨在 `premarket.py` 规则24 末尾同步同口径一句（盘前 prompt 无独立
规则25 条文，宏观检验挂在规则24 归因前置内）。

### 归因审计项（09-18-capability-boundary → applied）

落点：`attribute.py` ATTR_PROMPT 新增审计项——AI 判断中 cycle_state 多指数
bottom_date/rebound_day 存在分歧时，检查是否选取了对预设结论最有利的单一指数
锚定（正确做法=给出区间或取中位并显式标注分歧）；存在单点锚定在 analysis 指出
并归「概念误用」。09-17（取超窗最长指数称「接近窗口末期」）与 09-18（创业板
14 天超窗锚定导出高位兑现）同触此型，属 recurring 纪律问题，符合 durable rule
标准。

### glossary 增补（09-17-glossary-patch 并入）

`up-glossary.md` 新增「盲判归因增补（2026年9月18日）」一节，收录
「缩量/放量（口径约束）」词条：环比口径与 60 日分位口径分开陈述，
「环比放量但低分位」禁止合成为「缩量」；「企稳」须价格证据，不得由未达放量
阈值反推。

### 判例记录（09-18-pattern-patch-note 的部分落地）

09-18 右侧信号群案例（首板66家环比+28、封板率回升5.58pct、成交额环比+13.9%、
双指数收复5日线仍锁「调整」）记入 `reasoning-patterns.yaml` sentiment_cycle
known_failures，作为规则38 的对照样本，供后续裁决引用。

## 暂缓项与重启条件

以下三份标 **pending**（非 rejected），重启需满足样本条件：

- `2026-09-18-pattern-patch-stage.md` / `2026-09-18-glossary-patch-note.md`
  （规则38 证据清单修订 + 宏观利率分层）：再出现 ≥1 次同型误判（调整锁死、
  真值震荡）即重启裁决；届时 09-18 案例已有两个独立样本支撑。
- `2026-09-18-pattern-patch-note.md`（右侧信号量化阈）：先以判例形式积累
  ≥3 个右侧信号群在场的日子，观察「≥4 项触发」的区分度，再决定是否固化。
- 其中一点概念澄清先行确认（无需等样本）：**结构信号「未刷新为 invalidated」
  ≠ 压制成立**，陈旧信号不得作为当期方向约束——已写入 known_failures 判例
  表述，重启规则38 修订时并入正式条文。

## 实施清单（已执行）

1. `replay.py`：`_V19_RULE25_NEW` 追加三态计票口径（锚点 assert 不动，
   v15 冻结臂不受影响）。✅
2. `premarket.py`：规则24 末尾同步计票口径一句。✅
3. `attribute.py`：ATTR_PROMPT 新增分歧锚定审计项。✅
4. `up-glossary.md`：新增 9月18日增补节「缩量/放量（口径约束）」词条。✅
5. `reasoning-patterns.yaml`：sentiment_cycle known_failures 追加 2026-09-18
   案例。✅
6. 六份原提案 frontmatter 改标（1 applied + 2 merged + 3 pending，
   adjudication 字段回指本文档）。✅
7. `status.py`：提案统计行补 pending 计数显示。✅
8. 验证：`pytest tests/investment_engine/`（含规则25/38 锚点断言）+
   `validate_patterns_file` 整文件校验 + 状态报告重生成。

## prompt 同步检查（AGENTS.md 要求）

本次改动不涉及输出 JSON 字段与 11 项框架结构，`market_analysis_framework.txt`
与 `market_analyst.txt` 无需同步。

## 不在本裁决范围

- open 提案队列积压（本裁决前 65 份）：提案生成速度快于裁决速度，建议后续
  按错因簇定期合并裁决（本文与 09-12 裁决即此模式）；是否对归因侧做
  「同簇自动合并」节流，另立项评估。
- `2026-09-09-data-channel-note.md`（open）：维持 09-12 裁决结论，待数据源。
