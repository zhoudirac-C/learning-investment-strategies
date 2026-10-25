# 毕业判据 3（路径 A 假设证伪率）可计算定义 — 设计文档

日期：2026-10-25
状态：已与用户对齐（"两个都安排上"），实施中
前置：M3 claims 分桶 + 市场结果回写已于 2026-10-24 落地
（spec `2026-10-24-m3-outcome-writeback.md`）
修订对象：`2026-08-09-m4-graduation-check-design.md` 的"第三判据 v1 跳过"决策

## 背景

主计划 10.4（`investment-learning-project/ai-stock-investment-plan.md`）毕业标准第三条：
"路径 A 建议的假设证伪率不高于历史基准 +10pct"。M4 预备判分器 v1 因"路径 A 假设
无可计算定义"固定输出 pending-definition。M3 回写落地后，"假设 + 市场结算"的双侧
载体都已存在，本设计给出 v1 可计算口径。

## 关键决策

| 决策点 | 结论 |
|---|---|
| "假设"的 agent 臂载体 | shadow 预测 directions：prompt 规则 29 强制每条方向带可证伪失效条件，是 agent 臂"假设"的最接近载体。v1 **不区分路径 A/B**（shadow 输出无 path 字段），全部已结算方向计入，口径限制如实写明 |
| "证伪"的结算口径 | 市场结算 miss：与 M3 claims 回写同口径（5 交易日 forward 相对沪深300 超额为负）。这是**市场结算口径**的证伪，非框架原义"置信度跌破 40%"口径——后者需 agent 自产 claims 入库后才能计算，列入 v2 |
| agent 证伪率 | 判据 2 同窗同数据：窗口内 scored 方向 1 − 命中率（分母=已结算方向样本；与判据 2 完全一致） |
| 历史基准 | `knowledge/claims` up 桶全历史已结算证伪率 miss/(hit+miss)。claim 卡↔假设清单映射是原框架 v3.0 §3.5 明确指定的（statement→假设内容、status→验证状态、supersedes→证伪后修正），up 桶即"历史假设"库。须带 direction 块（无方向的 claim 不是可证伪假设）；neutral/pending/insufficient 不入分母（与 `evaluate_vs_market.py` / `up_hit_profile.py` 同口径）。2026-10-24 现状：300/518 = 57.9% |
| 达标线 | agent 证伪率 ≤ 基准 + 10pct |
| 数据不足处理 | 任一侧 n=0 → 该项输出 insufficient 且 **verdict 不得为 graduated**（保守，与 insufficient_data 同等效力） |
| 是否参与 verdict | 参与。graduated = 三项全过（与主计划 10.4 一致） |

## 数据流

```
evals/shadow/predictions/*.json（窗口聚合，复用判据 2 数据）
knowledge/claims（claim_buckets.load_claims → up 桶 → direction 非空且
  outcome.result ∈ {hit, miss} → miss/(hit+miss)）
→ criterion3(agent 证伪率, 基准) → {agent, baseline, threshold, passed}
→ judge：graduated 需 stage/direction/c3 全过
→ logs/graduation-<run_date>.md 输出数值与口径注记
```

## 组件变更

- `src/investment_engine/shadow/graduation.py`：
  `load_baseline(claims_dir)`、`criterion3(direction_stats, baseline)`、
  `judge(..., c3_passed)`（keyword-only 必填）、`render_report(..., c3)`、
  `run(..., claims_dir)`。
- `scripts/graduation_check.py`：`--claims-dir`（默认 `knowledge/claims`）。

## 口径注记（报告固定输出）

- 市场结算口径 ≠ 置信度口径；"路径 A/B 细分"待 shadow 输出增加 path 字段（v2）。
- 基准为 up 桶全历史累计（ Settlement 自 2026-04-27 窗口起），不随 8 周窗口滚动。
- technical-knowledge/缠论教材卡无 direction/outcome，天然不入基准（实测 settled=0）。

## v2 待办（本设计不实现）

1. shadow directions 增加 `path` 字段（A=基本面驱动 / B=情绪驱动），按路径细分证伪率；
2. 失效条件机械/LLM 结算通道（watch_next/invalidation 逐条到期核验）；
3. 置信度口径证伪（agent 自产 claims 入库后，对照"置信度跌破 40% 判失效"框架原义）。

## 测试

- baseline：yaml/md fixture 混合桶/混合 outcome（hit/miss/neutral/pending/insufficient、
  无 direction、research 桶）→ 只计 up 桶带 direction 的 hit/miss；
- criterion3 数学：命中率→证伪率、阈值、边界（n=0 → passed=None）；
- judge：c3 False / None 均阻断 graduated；
- 报告：含判据 3 数值行；数据不足时输出 insufficient 说明；
- run e2e：predictions + claims fixture → 报告出数；
- 回归：`tests/investment_engine` 全绿。

## 验收

1. 对真实数据跑 `graduation_check.py`，判据 3 输出 agent ≈59.1%（n=93）vs 基准 57.9%
   （n=518）、阈值 67.9%、达标，verdict 不变（not_yet，由判据 2 决定）；
2. 新增测试全绿，存量 judge 测试适配后全绿。
