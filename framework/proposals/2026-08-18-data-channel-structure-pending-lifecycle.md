---
date: 2026-08-18
type: data-channel
status: proposed
source: evals/shadow/attributions/2026-08-18.json
---

# 顶底结构"钝化中"中间态与生命周期表达

## 分析

UP 2026-08-18 早盘：「今天有可能会出现60分钟级别的顶部钝化，如果形成对应调整时间是3天」；
盘中 13:31：「若下午继续走弱，60分钟高9就不成立……等60分钟DIF拐头向下、顶部结构确认成立后
再处理；若下午涨速转快，60分钟顶部钝化则会自然消失」——钝化/高9 是**有生命周期的中间态**
（钝化中 → 确认成立 | 自然消失），且确认后对应可量化的调整窗口（60min 顶 → 约 3 天）。

现有 structure 块已具备部分能力：科创50 60min 顶部 `state=divergence`（2026-08-18 10:30）
已被识别。缺口在：

1. 无高9 / 序列计数表达（UP 的「60分钟高9不成立」无法映射）；
2. 无生命周期状态机：`forming → confirmed | invalidated` 及对应的理论调整窗口字段
   （当前只有 top/bottom 两态 + divergence 标记，无「可能消失」的表达）；
3. 已识别信号未被下游消费：8-18 盘后盲判未引用科创50 60min 钝化（规则引用缺失，
   已在当日归因记录）。

## 处置建议

1. structure 识别器增加生命周期字段：`state ∈ {forming, confirmed, invalidated}` +
   `adjust_window_days`（如 60min 顶 → 3 天，120min 顶 → 约 6-9 天，按级别映射）；
2. 评估接入高9/序列计数的可行性（TDX 序列数据或自实现九转计数），不可行则如实记录边界；
3. prompt 规则补充：structure 块含 `state=forming/divergence` 的顶部信号时，
   stage_reason 或 watch_next 必须引用（并入盲判 prompt 规则，与修复项
   `2026-08-18-fix-deterministic-output-validation.md` 的引用校验联动）。
   **✅ 已实施（2026-08-19）**：prompt v7 规则17（盘后/盘前双路）+ 校验层规则17 引用检查。
