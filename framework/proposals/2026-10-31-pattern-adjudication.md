# 2026-10-31 推理模式批量裁决（强趋势 1/2/3 · 交易之道 · 量价关系1）

date: 2026-10-31
type: pattern-adjudication
status: pending-human-approval
scope: framework/proposals/ 下 5 份提名文件，共 13 个候选
decision_rule: 复用性 / 可盘面判定 / 不重复 / 可证伪 / 不把课程个案当胜率

> 本文件只做裁决与暂存，不修改 `framework/reasoning-patterns.yaml`。
> 通过后由 `framework/proposals/2026-10-31-pattern-staging.yaml` 批量入库。

---

## 一、裁决结论（13 个候选 → 6 个新模式 + 2 项降级）

| # | 来源提案 | candidate_pattern_id | 裁决 | 去向 |
|---|---|---|---|---|
| 1 | 强趋势3 候选1 | strong_trend_participation_decay_20260823 | **合并** | N1 强趋势阶段与新鲜度资格 |
| 2 | 强趋势3 候选2 | first_bearish_candle_eligibility_20260823 | **合并** | N2 反馈退出与首阴资格 |
| 3 | 强趋势3 候选3 | low_quality_entry_filter_20260823 | **合并** | N3 参与模式选择（机会成本段降方法论） |
| 4 | 强趋势3 候选4 | panic_first_drop_vs_confirmed_weakness_20260823 | **入库** | N5 首次恐慌与明确走弱分层（限次新龙头） |
| 5 | 强趋势1 候选1 | pretrade_risk_feedback_exit_20260719 | **合并** | N2 反馈退出与首阴资格 |
| 6 | 强趋势1 候选2 | maturity_stage_core_rotation_20260719 | **合并** | N1 强趋势阶段与新鲜度资格 |
| 7 | 强趋势1 候选3 | rebound_second_wave_validation_20260719 | **入库** | N4 反弹性质分层（反抽/修复/新趋势/二波） |
| 8 | 强趋势2 候选1 | two_feedback_stop_framework_20260722 | **合并** | N2 反馈退出与首阴资格 |
| 9 | 强趋势2 候选2 | cognition_tier_risk_allocation_20260722 | **降级** | methodology（operation 章节），不进 pattern |
| 10 | 交易之道 候选1 | trend_stage_signal_freshness_20260624 | **合并** | N1 强趋势阶段与新鲜度资格 |
| 11 | 交易之道 候选2 | chase_dip_rolling_mode_20260624 | **合并** | N3 参与模式选择 |
| 12 | 交易之道 候选3 | behavior_constraint_risk_allocation_20260624 | **降级** | methodology（自我适配章节），不进 pattern |
| 13 | 量价1 候选 | volume_price_regime_validation_20261003 | **拆分** | 可计算增量→N6 基准量分档；位置解释→并入既有 volume_source_qualify / position_context_qualify |

**为什么不按 13 条原样入库**：第 1/5/6/8/10 条回答的是同一个问题「强趋势走到哪、还能不能拿」；
第 2/5/8 条共用同一条核心纪律「只有两次反馈，没有第三反馈」；
第 3/11 条都在回答「这个位置用什么方式参与」。原样入库会让同一问题命中 3 条 pattern，
检索时互相稀释，且后续维护要改三处。

**为什么 9/12 不进 pattern**：两者的判定输入是「用户自我认知/行为偏差」，无法用盘面数据客观判定，
违反「触发条件必须是客观数据特征」。放进 pattern 会让「我该不该重仓」这类问题命中一堆心理建议。

---

## 二、两条 CONTRADICTS 的裁决（本次新 claim 触发）

### 冲突 A：`claim-20260630-008-c`（减仓首日先砍一半） vs `claim-20261019-005-e`（一买一卖不必当日完成）

- **判定：非真矛盾，属触发源不同**。前者讲「形态信号触发的减仓」（K 线信号成立即执行），
  后者讲「日内做 T 回合」（成本驱动、可跨日）。
- **处置**：两条都保留 active，在 pattern 层写成分层规则（N2 第 5 步）：
  「信号驱动的减仓当日执行；做 T 回合允许跨日，但不得用于规避信号减仓」。
- 不建议 supersede：删任一条都会丢掉一个真实场景。

### 冲突 B：`claim-20260630-009-b`（缩量=假信号） vs `claim-20260812-027`（缩量上行非弱）

- **判定：非真矛盾，属位置不同**。形态反推场景（刺透/乌云第二根）缩量=反推无力；
  上涨趋势途中缩量=筹码稳定、无抛压。
- **处置**：两条保留，N6 第 2 步固化对照表「同一量能信号在两场景下含义相反」，
  检索时按「位置」分流，而不是按「缩量是好是坏」一刀切。

---

## 三、6 个拟入库模式一览

| ID | 名称 | 一句话职责 | 来源候选 |
|---|---|---|---|
| N1 | strong_trend_stage_qualify | 这波强趋势走到哪、还能不能追 | 1,6,10 |
| N2 | strong_trend_feedback_exit | 买入后反馈不达标，何时退、退多少 | 2,5,8 |
| N3 | strong_trend_entry_mode | 这个位置用追高/低吸/滚动哪种方式参与 | 3,11 |
| N4 | rebound_second_wave_qualify | 暴跌后的反弹是反抽、修复、新趋势还是二波 | 7 |
| N5 | panic_first_drop_vs_weakness | 次新龙头首次跳水 vs 已明确走弱，处置不同 | 4 |
| N6 | volume_benchmark_levels | 成交量是否达到推升量/出货量级别（可计算） | 13 的可计算部分 |

完整字段见 `framework/proposals/2026-10-31-pattern-staging.yaml`（已过 `pattern_schema` 校验）。

---

## 四、入库前仍需人审的 3 个口径

1. **N6 的公式系数未经课件画面校订**：「凹动量」「极动量」为 ASR 音译，1.382 / 0.618 / 0.5 三条线
   需回看视频画面确认边界是否含等号。当前 `validation.known_failures` 已标注，入库后也应挂 provisional。
2. **N5 的适用范围**：是否限定「次新龙头」，还是放宽到所有高辨识度标的？建议先限次新，避免与 N2 重叠。
3. **N4 与既有 `position_by_cycle` 的边界**：N4 只做「反弹性质定性」，不出仓位动作；
   仓位动作一律走 position_by_cycle。若认可，则在 N4 的 falsification 里写死这条分工。

---

## 五、通过后的执行动作

1. 把 staging 里 6 条 append 到 `framework/reasoning-patterns.yaml` 的 `patterns` 列表；
2. 运行 `validate_patterns_file` 全量校验；
3. 5 份原提案文件 `status: proposed → adjudicated`，并回写去向；
4. 2 项降级内容写入 `methodology/` 对应章节（另起一次文档变更）；
5. git commit + push。
