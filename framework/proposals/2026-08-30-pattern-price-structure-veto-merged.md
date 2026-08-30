---
date: 2026-08-30
type: pattern-patch
status: applied
source: [evals/shadow/attributions/2026-08-24.json, evals/shadow/attributions/2026-08-25.json]
merged_from: [2026-08-24-pattern-patch-note.md, 2026-08-25-pattern-patch-note.md]
---

# 合并裁决：价格结构前置否决（SYSTEM_PROMPT 规则28，prompt v12）

## 裁决结论

两份提案同根（均指向「宽度/情绪指标压过价格结构」这一失败模式），合并回写为
`src/investment_engine/blindtest/replay.py` SYSTEM_PROMPT 规则28 +
`validate_result` 机械校验（规则28），prompt 版本 v11 → v12。原两份提案保留作溯源，处置以本文为准。

## 同根分析

- 08-24（盘前判震荡/缩量企稳，真值调整）：顶部结构、超窗口反弹只进 watch_next 不进结论；
- 08-25（收盘判震荡/缩量企稳，真值调整）：宽度修复（涨4234家/涨停65家）盖过创业板指 -1.00% 仍收跌，
  invalidation 缺价格确认判据。

合并后规则两条主干：(a) 破位校验——核心指数跌破 5 日均线/近期波段低点且当日收跌时，宽度修复只按反抽处理，
禁止「缩量企稳」，stage 优先「调整」；(b) 顶部结构结论级压制——规则17 只要求引用，规则28 要求影响结论
（顶部结构在位禁判主升；叠加破位或反弹超窗口优先判调整）。

## 回测证据（决定机械校验口径的关键）

对全部 28 条影子盲判记录（08-07~08-28）回测候选机械条件：

| 候选条件 | 抓住判错 | 误伤判对 |
|---|---|---|
| 任一核心指数破位 | 2（08-24pre/08-25） | 4（08-19~08-21 磨底期） |
| 双核心指数破位 | 2 | 4（同上） |
| **双破位 + 创业板指当日收跌（采纳）** | **2** | **0** |

磨底期（08-19~08-21）双破位下判「震荡/缩量企稳」是**对的**——机械否决企稳会把磨底正确判断错杀，
故机械层只拦「双破位+收跌」这一最高置信形态；单破位、破位收涨等分歧情形交给 prompt 条文引导
（要求 stage_reason 写明破位事实与收复条件），不做机械否决。

## 回写位置

- prompt 规则28：`src/investment_engine/blindtest/replay.py` SYSTEM_PROMPT（v12）；
- 机械校验：`validate_result` 规则28 分支 + `_index_broken`/`_index_down` 辅助函数；
- 测试：`tests/investment_engine/test_validate_result.py::TestPriceStructureVeto`（6 例，含假阳防护回归）。

## 边界

- 本规则不解决「08-19/08-20 收盘把震荡误判为调整」的反向错判（过度悲观），那是另一类失败模式；
- 配套的「缩量企稳」词条修订（2026-08-24/2026-08-25-glossary-patch-note）仍 open，待人工另行裁决。
