---
date: 2026-08-14
type: pattern-patch
status: merged
merged_into: framework/proposals/2026-08-30-direction-invalidation-merged.md
source: evals/shadow/attributions/2026-08-14.json
---

# 设置方向失效条件

## 分析

AI判断市场为震荡且主动降速，但实际5G和CPO方向均跑输基准，方向判断错误。AI依赖的推理步骤中，对情绪退潮的解读过于乐观，未充分验证主线方向的持续性。具体而言，AI在判断5G和CPO方向时，仅基于昨日涨停和隔夜外盘，未考虑当日开盘后的实际走势确认，且未设置方向失效的明确条件。此外，AI的cycle_state中rebound_day已超理论窗口，但未将此信号转化为对方向的直接否定，导致方向判断失误。

## 处置建议

为每个方向设置明确的失效条件，如跌破关键支撑位或连续两日跑输基准，一旦触发则立即切换方向判断。

> merged 2026-08-30：与 08-11/12/14 三份方向层提案合并裁决，回写为 SYSTEM_PROMPT 规则29「方向必须带失效条件」（prompt v13，盘前/盘后双轨同步），详见 framework/proposals/2026-08-30-direction-invalidation-merged.md。
