# M3 前置（第一期）：推理模式 validation 回填与提案机制 — 设计文档

日期：2026-08-08
状态：已与用户对齐，待写实施计划
分支：`feat/m3-pattern-validation`

## 定位与边界

主计划（`investment-learning-project/ai-stock-investment-plan.md` 第十四节）的 M3
是"信号回写底座化"：claims 按 source 分桶、市场结果回写置信度、
`evaluate_vs_market.py`、研报管线扩容。其中 claims 分桶与 UP 画像依赖 M2 影子
双轨约 4 周数据积累（2026-09 初），**不在本期**。

本期是 M3 的可提前切片，只做两件事：

1. **M1 盲测结果回填** `framework/reasoning-patterns.yaml` 的 `validation` 区块
   （8 个模式挂着 `pending-m1` 的债）；
2. **提案制回写机制**（生成器 + 人工评审 + 执行器），为影子期的持续回写打底。

本期不做：claims 分桶、`evaluate_vs_market.py`、研报管线、影子数据自动分桶、
每日自动提案；不改 `src/qing_investment/`。

## 现状事实（设计依据）

- `framework/reasoning-patterns.yaml` 10 个顶层模式：
  - `technical_timing`、`operation_strategy` 已有 M0 真实回测命中率（0.5182，
    直接机械回测，证据强度高于盲测使用归因）；
  - 其余 8 个 `historical_hit_rate: pending-m1`，`applicable_regime: null`，
    `known_failures: []`（`others` 的 known_failures 非空）。
- M1 盲测产物 `evals/blindtest/results.jsonl`（71 天，2026-04-27 ~ 2026-08-07），
  每日记录 `used_patterns`。窗口内实际被使用的模式 6 个：
  `upstream_cycle / mainline_identification / sector_rotation /
  sentiment_cycle / technical_timing / ai_industry_chain`；
  未被使用 4 个：`macro_transmission / earnings_analysis /
  operation_strategy / others`。
- `src/investment_engine/blindtest/score.py` 评分函数均接受 results 列表：
  `stage_accuracy(results, truth)`、`direction_scores(results, *, config_dir,
  db_path, ...)`、`stock_scores(results, *, db_path, ...)`——按 used_patterns
  过滤 results 后可直接复用，口径与 M1 基线完全一致。
- schema 约束（`src/investment_engine/distill/pattern_schema.py`）：
  `historical_hit_rate` 只允许 `null / 数值 / "pending-m1"`，**不改**。
- 无 Neo4j/Qdrant 同步管线消费 reasoning-patterns.yaml（仅
  `src/qing_investment` 运行时读取），回写自包含，无后续同步义务。

## 关键决策（已与用户对齐）

| 决策点 | 结论 |
|---|---|
| 范围 | 只做 patterns，不动 knowledge/claims |
| historical_hit_rate 形态 | 标量（主指标数值），明细外挂提案存档，不改 M0 校验器 |
| 分桶阈值 | 宽松三桶：达标=主指标≥毕业线且 n≥20；证伪=主指标<50% 且 n≥20；其余待观察 |
| 架构 | 独立包 `src/investment_engine/pattern_eval/` + 两个 thin script |

## 架构与数据流

```
evals/blindtest/results.jsonl
  → attribute.py   按 used_patterns 分组，复用 blindtest/score.py+truth.py
                   算每模式三指标 + 分环境段明细
  → bucket.py      主指标映射 + 宽松三桶规则 → 桶判定
  → proposal.py    渲染提案 YAML → framework/proposals/<date>-pattern-validation-m1.yaml
  →（人工评审提案文件）
  → apply.py       校验提案 → 应用 → 整文件 pattern_schema 再校验
  → framework/reasoning-patterns.yaml
```

新包 `src/investment_engine/pattern_eval/`，四模块各单一职责、纯函数优先：
（指标计算与分桶不依赖文件路径之外的全局状态，影子期可直接复用。）

脚本：
- `scripts/propose_pattern_validation.py [--results evals/blindtest/results.jsonl]
  [--patterns framework/reasoning-patterns.yaml] [--out framework/proposals/]`
- `scripts/apply_pattern_proposal.py <proposal.yaml> [--dry-run]
  [--patterns framework/reasoning-patterns.yaml]`

## 指标与归因口径

- 对 6 个被使用模式，各算三项指标（样本数随模式使用天数变化）：
  阶段一致率、方向 5 日超额命中率、标的 5 日超额命中率，以及按真值标签的
  分环境段一致率（主升/恐慌/调整/震荡）。
- **归因口径 = 使用归因**：当日预测命中归给当日 `used_patterns` 里的每个模式；
  同日多模式共用时**不隔离**单模式贡献。该口径限制必须在提案 evidence 区块
  如实标注。
- 无效日（`ok=False` / `error` / `invalid`）没有可解析的 `used_patterns`，
  不归入任何模式的样本——即 per-pattern 分母只含成功解析出该模式的日子，
  与 M1 总体口径的分母（71 天含无效日）不同，提案 evidence 中需注明此差异。

## 主指标映射与三桶规则

主指标决定桶归属（判断依据：各模式 steps 的最终产出物）：

| 模式 | 主指标 | 毕业线 |
|---|---|---|
| sentiment_cycle | 阶段一致率 | 70% |
| mainline_identification | 方向 5 日超额 | 60% |
| sector_rotation | 方向 5 日超额 | 60% |
| upstream_cycle | 方向 5 日超额 | 60% |
| technical_timing | 标的 5 日超额 | 55% |
| ai_industry_chain | 标的 5 日超额 | 55% |

毕业线出处：阶段 70%、方向 60% 来自主计划 10.4；标的无官方毕业线，
取 55%（M1 基线 56.6% 附近，且显著高于随机 50%）——本表即该线的定义出处。

三桶（n = 该模式使用天数中可评分样本数）：

- **达标**：n ≥ 20 且主指标 ≥ 毕业线；
- **证伪**：n ≥ 20 且主指标 < 50%（掷硬币水平以下）；
- **待观察**：其余（含 n < 20、介于 50% ~ 毕业线之间）。

## 回写动作

| 对象 | 动作 |
|---|---|
| 被使用且无实测值的 5 个模式 | `historical_hit_rate` ← 主指标实测标量（不论桶）；`applicable_regime` ← 分环境段一致率映射；仅证伪桶向 `known_failures` 追加一条（含指标、样本数、窗口） |
| `technical_timing` | **不动**（已有 M0 直接回测值 0.5182，证据更强）；盲测指标仅录提案证据区。apply 的当前值守卫自然 SKIP |
| 未被使用的 4 个模式 | 不动，保持 `pending-m1` 等影子期；提案证据区标注 "m1 未使用" |

`pending-m1` 语义即"未测量"；凡测过即写数，桶只影响注解，不影响是否写数。

## 提案文件格式

`framework/proposals/20260808-pattern-validation-m1.yaml`：

```yaml
proposal_id: 20260808-pattern-validation-m1
source: m1-blindtest
generated_at: <ISO 时间>
evidence:
  window: {start: 2026-04-27, end: 2026-08-07, trading_days: 71}
  attribution: 使用归因（同日多模式共用，未隔离单模式贡献）
  metrics:
    <pattern_id>:
      days_used: <int>
      primary_metric: stage_consistency|direction_excess|stock_excess
      stage: {rate: <float>, n: <int>}
      direction: {rate: <float>, n: <int>}
      stock: {rate: <float>, n: <int>}
      regime: {主升: {rate: , n: }, 恐慌: {...}, 调整: {...}, 震荡: {...}}
      bucket: 达标|待观察|证伪
    <unused_pattern_id>: {bucket: unused, note: m1 未使用}
changes:
  - pattern_id: <id>
    set:
      validation.historical_hit_rate: <float>
      validation.applicable_regime: {<regime>: <float>, ...}
    append_known_failures: [<str>]   # 仅证伪桶
```

提案是人审界面：证据区全量留档（含不改 yaml 的模式），changes 区只含
实际要落库的补丁。

## apply 安全性

1. 应用前：整文件过 `pattern_schema.validate_patterns_file`；提案每个
   `pattern_id` 必须存在于 yaml；目标字段当前值守卫——
   `historical_hit_rate` 必须是 `"pending-m1"`，`applicable_regime` 必须是
   `null`，`known_failures` 追加只允许空列表或已含非重复条目——不满足则该条
   SKIP 并打印原因（天然幂等：同一提案跑两次，第二次全 SKIP）。
2. 只改 validation 三个子字段，其余字段一律不碰。
3. 应用后整文件再过一次 schema 校验，失败则拒绝写盘并报错。
4. `--dry-run` 打印将发生的变更不落盘；正式应用后由人 `git diff` 确认提交。

## 测试

- `test_attribute.py`：合成 results.jsonl fixture（含多模式共用、ok=False 日），
  验证分组、三指标计算与 score.py 口径一致；
- `test_bucket.py`：阈值边界（n=19/20，rate=0.699/0.70、0.599/0.60、
  0.549/0.55、0.499/0.50），主指标映射表完整性（6 模式全覆盖）；
- `test_proposal.py`：渲染结构快照（evidence/changes 分区、unused 标注、
  technical_timing 只进证据区）；
- `test_apply.py`：临时 yaml 副本上的应用 + 双次 schema 校验、幂等 SKIP、
  未知 pattern_id 拒绝、非 pending-m1 字段守卫 SKIP、dry-run 不落盘；
- 全量回归：`PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q`
  （基线 561 passed + 4 个已存在环境型失败）。

## 错误处理

- results.jsonl 缺行/坏行：attribute 阶段如实跳过并计数，进提案 evidence；
- K 线缓存缺数据导致无法评分：沿用 score.py 既有口径（该样本不计入分子），
  不静默改口径；
- 提案 yaml 结构不合法：apply fail-fast，不部分应用。

## 验收标准

1. 生成器对真实 M1 数据跑出提案，6 个被使用模式指标齐全、unused 4 个有标注；
2. 人工评审后 apply 落库：5 个模式写实测值，technical_timing 与 4 个未使用
   模式不动；整文件过 pattern_schema 校验；
3. 提案文件、apply 后 yaml、diff 一并 commit；
4. 新增测试全绿，全量回归不退化（561+新增 passed，4 个基线失败不变）。
