---
date: 2026-08-30
type: pattern-patch
status: applied
source: [evals/shadow/attributions/2026-08-11.json, evals/shadow/attributions/2026-08-12.json,
  evals/shadow/attributions/2026-08-14.json]
merged_from: [2026-08-11-pattern-patch-note.md, 2026-08-12-pattern-patch-note.md,
  2026-08-14-pattern-patch-note.md]
---

# 合并裁决：方向失效条件（SYSTEM_PROMPT 规则29，prompt v13）

## 裁决结论

三份提案同为方向层判错（direction_miss）归因，合并回写为 SYSTEM_PROMPT 规则29
「方向必须带失效条件」（盘后/盘前双轨同步），prompt 版本 v12 → v13。
原三份提案保留作溯源，处置以本文为准。

## 同根分析与既有覆盖核对

- **08-14（方向失效条件）**：最干净的增量——directions 只给看多理由、不带失效条件，
  现行 28 条规则无任何一条覆盖。采纳为规则29 主干。
- **08-11（板块持续性验证）**：连板高度/封板资金已被规则16（梯队引用）覆盖；「板块与
  大盘共振」增量薄弱，并入规则29 失效条件口径（「板块与大盘背离放大则退潮」）。
- **08-12（流动性风险预警）**：成交额萎缩 + 指数压力位已被规则20（量能台阶锚定）与
  规则28（破位前置否决）覆盖；残余增量并入规则29（「成交额连续萎缩则降 posture」
  类失效条件）。

## 背景指标

方向层是盲判最弱环：毕业报告（logs/graduation-2026-08-24.md）方向 5 日超额命中率
28.6%（n=14，毕业线 60%）。规则29 不改变方向选择本身，只强制每个方向携带可证伪的
退出条件，为方向层归因提供对照锚点（选了且说了何时错，才谈得上复盘修正）。

## 回写位置

- prompt 规则29：`src/investment_engine/blindtest/replay.py`（盘后）与
  `src/investment_engine/shadow/premarket.py`（盘前，昨日口径）；
- **不做机械校验**：失效条件表述多样（价位/均线/跑输基准/断板/量能），关键词校验
  误伤面大；先 prompt 引导，观察一周（~09-06）后依 validation 与判错形态再评估机械化。

## 边界

- 不新增 directions 输出字段（失效条件写在 reason 末尾），避免契约变更；
- 方向超额命中率是否改善，待本周（08-24 起）T+5 回填后在周报验证。
