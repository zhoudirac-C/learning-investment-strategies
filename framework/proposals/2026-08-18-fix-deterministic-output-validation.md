---
date: 2026-08-18
type: fix
status: implemented（2026-08-19，见下方实施记录）
source: evals/shadow/attributions/2026-08-17.json + evals/shadow/attributions/2026-08-18.json
---

# 盲判输出确定性校验层（规则遵守的机械兜底）

## 背景

连续两日同类型失效，表明仅写入 prompt 的规则依赖模型自觉、无强制力：

- 2026-08-17（规则7）：cycle_state.rebound_day=11 ≥ 8 且超窗口，要求 position 优先判
  「反弹超预期」，实际输出「震荡调整」（同版本 8-14 曾正确执行，属执行回归）；
- 2026-08-18（规则15/13/16）：rules 13-16 当日 08:28 已全量合入 prompt v6，盘后盲判情形A/B
  仍挂「成交额24000亿/22000亿、创业板指3740/3700」绝对阈值——24000 亿正是规则15 的反例原文；
  且 lhb.jgmmtj、limit_pool.ladder、structure 顶部钝化全在包内（missing=None）而输出均未引用。
  同日盘前(-pre)遵守规则15、盘后违反——同一 prompt 下执行不稳定。

## 处置建议

在 `parse_result` 之后增加确定性校验层（不调 LLM，正则/字段比对），premarket 与 daily 两路复用：

1. **阈值校验**（规则15）：scenarios / watch_next / invalidation 文本中「成交额(亿)」后紧跟
   具体数字、且非「前日量级」参照口径 → 判违规，打回重写一次（附违规说明），再犯则输出降级标注；
2. **引用校验**（规则13/16）：pack 含 limit_pool.ladder / lhb.jgmmtj / structure 顶部 forming 态，
   而输出未引用任一对应字段（字段名/内容关键词比对）→ 同上打回；
3. **一致性校验**（规则11a 机械化）：operation.position 与 market_stage 的矛盾对
   （如 主升 + 降仓位类 action）→ 打回。

实施位置：`src/investment_engine/blindtest/replay.py` 新增 `validate_result`，
`predict.py` / `premarket.py` 在 `parse_result` 后调用；配 `tests/investment_engine/` 用例
（含 8-17/8-18 两个真实违规样本作回归用例）。打回次数上限 1 次，避免死循环；
最终仍违规则如实落盘并标 `validation: failed`，不掩盖。

## 验收标准

- 8-17、8-18 两日真实违规输出重放时被拦截；
- 合规输出（如 8-18-pre）不误伤；
- 校验层本身零 LLM 调用。

## 实施记录（2026-08-19）

改动文件：

- `src/investment_engine/blindtest/replay.py`：新增 `validate_result`（三类校验）+
  `run_with_validation`（打回一次 → 仍违规标 failed 如实返回）；SYSTEM_PROMPT 新增规则17
  （顶部结构 forming/divergence 信号必须引用）；PROMPT_VERSION v6→v7；
- `src/investment_engine/shadow/predict.py` / `premarket.py`：接线 `run_with_validation`
  （`call_fn=call_deepseek` 保留测试补丁点），落盘记录新增 `validation` 字段；
  premarket prompt 同步新增规则17；
- `tests/investment_engine/test_validate_result.py`：19 用例（含 8-17/8-18 真实违规样本、
  重试/打回/failed 不掩盖路径）；`test_daily.py` / `test_premarket.py` 版本守卫 v6→v7 +
  规则17 关键词钉住。

验收结果：

- 342 个 investment_engine 测试全绿；
- 真实重放：8-17 盘后拦截 7 条（规则15×4 / 规则11 主升+降仓矛盾 / 规则10/12 冲量滑落+主升 /
  规则17），8-18 盘后拦截 5 条（规则15×3 / 规则13 / 规则17）；
- 8-18-pre 无规则15/规则11 误伤；规则13/17 各中 1 条属真实缺引用（机构席位、上证 60min 钝化——
  UP 当日早盘正是以 60min 钝化为主线判断），非误伤；
- 校验层纯正则/字段比对，零 LLM 调用；打回上限 1 次，仍违规落盘标 `validation: failed` 不掩盖。

已知边界（后续跟踪）：

- 规则17 依赖 structure 的 divergence 态：信号未确认/未消失期间会持续要求引用（每日可能多一次
  打回调用），待 `2026-08-18-data-channel-structure-pending-lifecycle.md` 的生命周期状态
  （confirmed/invalidated）落地后自然消解；
- 指数点位阈值（如 3740 点）未机械化（结构位 vs 非结构位无法机械区分），仍靠模型自觉。
