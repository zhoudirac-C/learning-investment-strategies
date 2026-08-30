---
date: 2026-08-11
type: pattern-patch
status: merged
merged_into: framework/proposals/2026-08-30-direction-invalidation-merged.md
source: evals/shadow/attributions/2026-08-11.json
---

# 增加板块持续性验证

## 分析

AI判断市场处于震荡阶段，但实际方向判断错误。在推理过程中，AI使用了情绪周期和主线识别框架，但缺少对市场整体趋势的确认步骤。具体而言，AI仅依据当日缩量下跌和涨停家数等短期情绪指标，未结合更长期均线趋势或市场宽度指标来确认市场阶段。此外，AI在方向选择上，虽然识别了医药和MLCC板块，但未考虑板块的持续性或与大盘的共振关系，导致方向判断失误。

## 处置建议

在识别主线方向时，需验证板块内涨停个股的连板高度和封板资金，并观察板块指数是否与大盘同步，若板块独立于大盘走强，需谨慎对待。

> merged 2026-08-30：与 08-11/12/14 三份方向层提案合并裁决，回写为 SYSTEM_PROMPT 规则29「方向必须带失效条件」（prompt v13，盘前/盘后双轨同步），详见 framework/proposals/2026-08-30-direction-invalidation-merged.md。
