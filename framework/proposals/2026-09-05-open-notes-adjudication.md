---
date: 2026-09-05
type: adjudication
status: applied
source: [evals/shadow/attributions/2026-08-26.json, evals/shadow/attributions/2026-08-27.json,
  evals/shadow/attributions/2026-08-28.json]
adjudicates: [2026-08-26-pattern-patch-note.md, 2026-08-26-data-channel-note.md,
  2026-08-27-pattern-patch-note.md, 2026-08-27-data-channel-note.md,
  2026-08-28-pattern-patch-note.md, 2026-08-28-capability-boundary-note.md,
  2026-08-28-glossary-patch-note.md]
---

# 合并裁决：08-26~08-28 七份 open 提案（W36 人审闭环）

## 背景

W36 盲判周（08-31~09-04）期间三份 open 提案的错误原样重演：稀缺资源
08-31/09-03/09-04-pre 三连选（reason 自述「无显性催化」，该方向历史 T+5 超额
0/4）；09-01 存储芯片隔夜映射当日被证伪（与 08-28 NVDA 映射同一失败模式）。
W36 人审结论：优先闭环。七份提案按落点合并处置如下，原提案保留作溯源，
处置以本文为准。

## 裁决明细

| 提案 | 结论 | 落点 |
|---|---|---|
| 08-27-pattern-patch（无显性催化禁维持方向） | applied | SYSTEM_PROMPT 规则36（盘前/盘后双轨），prompt v14→v15 |
| 08-26-pattern-patch（资金流二次验证） | applied | SYSTEM_PROMPT 规则37（双轨），prompt v14→v15 |
| 08-26-data-channel（global_macro 通道） | applied | 通道主体已建（08-20 提案落地：美股三指数/费半/存储链/亚太/美债 10Y30Y/美元指数已在 pack）；本次补 ^IRX 短端 + 商品组（黄金 GC=F、铜 HG=F） |
| 08-27-data-channel（大宗商品价格/库存） | partial | 期货价格由 GC=F/HG=F 闭环（COMEX 口径）；库存周度无免费公开通道，保留为数据缺口 |
| 08-28-pattern-patch（隔夜映射竞价验证） | merged | 并入 2026-09-05 W36 提案模式一窗口验证；竞价验证步骤划给盘中/监控轨 |
| 08-28-capability-boundary（隔夜映射边界声明） | applied | 并入规则30 末尾边界声明（双轨） |
| 08-28-glossary（放量攻击/存量腾挪） | applied | 回写 `framework/up-glossary.md`「盲判归因增补（2026年9月5日）」 |

## 要点说明

### 规则36（08-27 闭环）：无显性催化禁入选方向

规则23 原处置（注明「无显性催化」+ posture 不高于「波段」）被证明不足——
模型照章注明后仍三次入选稀缺资源。升级为直接排除；叠加 direction_track 块
（W36 已落地）的历史战绩引用义务：命中率=0 且样本 ≥3 的方向禁止入选，
坚持入选须在 reason 引用该读数并给出更强证据链。

### 规则37（08-26 闭环）：资金流性质二次验证

所需数据全部已在 pack（lhb.jgmmtj 机构净买卖家数、emotion.daban 封板率、
limit_pool 晋级率/first_board_width），无新数据依赖。机构净卖出家数占优或
宽度明显萎缩时按游资短线轮动嫌疑处理，资金流信号降权，该方向不得入选
directions（可写入 watch_next 观察）。

### global_macro 增补（08-26/08-27 data-channel 闭环）

- **13W 国库券（^IRX）**：Yahoo 无 2Y 符号，以 13W 近似短端，曲线形状以
  10Y−13W 粗看（W36 提案模式一数据缺口的「美债 2Y/曲线形状」按此口径落地）。
- **商品组**：黄金 GC=F、铜 HG=F（COMEX 期货口径；LME 无免费公开符号，
  口径差异如实注明）。美股三指数（标普/纳指/道指）此前已在 pack，
  模式一「源头宽基跌幅」数据缺口同时闭环。
- **库存周度**（LME/SHFE 库存）无免费公开 API 通道，保留为数据缺口；
  无商品价格条目支撑时，大宗周期方向按规则36「无显性催化」降级处置。
- 2026-09-05 实拉验证（sakura 代理）：13W 3.757（+1.7bp）/ 黄金 4429.8（-1.38%）
  / 铜 6.6（+0.3%）。

### 竞价验证（08-28 pattern → merged）

与 W36 模式一同构（冲击/映射都只定价开盘），窗口验证合并进行。竞价量价验证
（9:15-9:25 竞价时段）在盘前盲判轨不可执行——pack 数据截至昨日，该步骤划归
盘中/监控轨职责，盘前轨只承担规则30 的先验与边界声明。

### 能力边界（08-28 capability-boundary → applied）

并入规则30 末尾：依赖隔夜外盘映射/冲击的预判只覆盖开盘定价，不覆盖日内
反转风险，引用外盘映射时须显式声明该边界。

### glossary（08-28 → applied）

新增「放量攻击」词条（含存量语境禁用条件）；「存量腾挪」与既有词条
「换手（存量调仓）」（2026-08-17 增补节）同义，不单列新词条，以别称形式合并，
避免词典冗余。
