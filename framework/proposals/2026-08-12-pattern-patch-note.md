---
date: 2026-08-12
type: pattern-patch
status: merged
merged_into: framework/proposals/2026-08-30-direction-invalidation-merged.md
source: evals/shadow/attributions/2026-08-12.json
---

# 增加流动性风险预警

## 分析

AI判断市场处于震荡修复期，但实际次日市场下跌，且AI推荐的方向中PCB和存储板块跌幅显著大于基准，仅光通信方向跑赢。AI在推理中依赖了成交额、涨停潮等数据，但未考虑市场情绪可能已处于高位，且未对主线板块的持续性进行更严格的验证。具体而言，AI在识别主线时仅依据当日涨停和资金认可度，未纳入板块内个股的估值分位、前期涨幅、市场情绪周期位置等关键步骤，导致对PCB和存储板块的持续性判断失误。此外，AI在设定情形时未考虑成交额萎缩可能导致的流动性风险，且未对指数关键支撑位进行更细致的分析。

## 处置建议

在震荡判断中，若成交额持续萎缩且指数处于关键压力位，应预警流动性风险，并考虑降低仓位或回避高位题材股。

> merged 2026-08-30：与 08-11/12/14 三份方向层提案合并裁决，回写为 SYSTEM_PROMPT 规则29「方向必须带失效条件」（prompt v13，盘前/盘后双轨同步），详见 framework/proposals/2026-08-30-direction-invalidation-merged.md。
