# M4 预备：毕业判分器 — 设计文档

日期：2026-08-09
状态：已与用户对齐，待写实施计划
分支：`feat/m4-graduation-check`

## 定位与边界

主计划 10.4 的毕业标准（阶段一致率 ≥70%、方向 5 日超额 ≥60%、假设证伪率
≤基准+10pct，连续 8 周达标）目前没有任何代码在跟踪——影子双轨每日产数据，
但"离毕业还差多少"没有判据出口。本工具把毕业判定做成按需评估器：
数据不够时如实报告进度，数据够时直接出判决。

本期只做**判分器**；M4 的 prompt 改造本体属毕业后的动作，不在本期。
不挂 cron（按需手动跑，避免每日无意义重算）；不改 `src/qing_investment/`。

## 现状事实（设计依据，已核实）

- `evals/shadow/predictions/<date>.json` 记录结构（`shadow/predict.py` 写入，
  `shadow/maturity.py` 回填）：
  - `stage_hit`：bool 或 null（阶段真值次日可判，与 due_scores 结算节奏不同）；
  - `due_scores.directions / .stocks`：`{samples, hits, hit_rate}`，
    仅 `status == "scored"` 的记录有（5 交易日后由 maturity 回填，
    复用 `blindtest/score.py`，口径与 M1 基线一致）；
  - `status`：`pending_maturity / scored / error`。
- 毕业阈值出处：`investment-learning-project/ai-stock-investment-plan.md` 10.4；
  "连续 8 周（覆盖至少一次完整情绪周期）达标"。
- `logs/` 大部分被 .gitignore，但已有 `!logs/m1-*.md`、`!logs/shadow-status.md`
  例外先例——报告要进 git 需加同类例外。

## 关键决策（已与用户对齐）

| 决策点 | 结论 |
|---|---|
| "连续 8 周"口径 | 窗口聚合达标：最近 8 个自然周内已结算记录聚合算命中率，达标即过；附分周明细 |
| 第三判据 | v1 跳过：仓库中"路径 A 假设"无可计算定义，固定输出 pending-definition 及说明 |
| 架构 | `src/investment_engine/shadow/graduation.py` 单模块 + thin script |

## 数据流

```
evals/shadow/predictions/*.json
  → 解析（坏行/缺字段跳过并计数）
  → 归入 ISO 自然周，取最近 weeks 周窗口（默认 8）
  → 两项指标各自聚合
  → 判定 verdict
  → stdout 摘要 + logs/graduation-<run_date>.md
```

## 指标口径

- **阶段一致率**：`stage_hit` 非 null 的记录中 True 占比；n = 该记录数。
- **方向超额命中率**：`status == "scored"` 记录的 `due_scores.directions`
  跨日聚合 Σhits/Σsamples（与 M1 口径一致，非日均值）。
- 两项各自取 n（结算节奏不同），报告分别标注。

## 判定规则

窗口精确定义：从运行日往前数 weeks 个 ISO 自然周；**覆盖周数** = 窗口内有
记录的自然周数。节假日整周无记录会拉低覆盖周数——这是有意保守（"连续"
要求连续性），在报告中如实呈现。

| verdict | 条件（按序判定） |
|---|---|
| `no_data` | 窗口内两项指标样本均为 0 |
| `insufficient_data` | 覆盖周数 < weeks |
| `graduated` | 窗口满且阶段一致率 ≥ 0.70 且方向超额 ≥ 0.60 |
| `not_yet` | 窗口满但至少一项未达标 |

判据 3 固定输出 `pending-definition`："路径 A 假设证伪率"在仓库中无可计算
定义（待 M3 claims 分桶落地后定义），本版本不参与判定。

## 报告格式

`logs/graduation-<run_date>.md`：窗口范围（起止日期、覆盖周数）、两项指标
rate/n、分周明细表（每周的阶段/方向样本与命中率）、verdict、判据 3 说明、
口径注记（使用 shadow 双轨数据，非 M1 历史回放）。

`.gitignore` 加例外 `!logs/graduation-*.md`。

## 组件

- `src/investment_engine/shadow/graduation.py`：
  `load_records(pred_dir) → list[dict]`、`window_weeks(records, weeks) → dict`
  （周分组）、`aggregate(records) → dict`（两项指标）、
  `judge(stats, weeks) → str`、`render_report(...) → str`、
  `run(pred_dir, weeks, out_dir) → Path`。
- `scripts/graduation_check.py`：`[--pred-dir evals/shadow/predictions]
  [--weeks 8] [--out-dir logs/]`，打印摘要返回 0。

## 测试

- fixture 在 tmp_path 构造 predictions JSON 文件：scored/pending_maturity/
  error/缺字段/坏 JSON 混合；
- 聚合数学精确断言（手工算得的比例）；
- 窗口边界：7 周数据 → `insufficient_data`；8 周达标 → `graduated`；
  8 周未达标 → `not_yet`；空目录 → `no_data`；
- 报告含分周明细与判据 3 说明；
- CLI 冒烟：写报告文件、stdout 含 verdict。

## 错误处理

- 坏 JSON / 缺 date 字段：跳过并计数，进报告"解析跳过 n 条"注记；
- pred_dir 不存在：`no_data`，返回 0（不出异常，允许在数据未积累时跑）；
- 全量回归：`PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q`
  （基线 589 passed + 3 个已存在环境型失败）。

## 验收标准

1. 对真实 `evals/shadow/predictions/`（当前 1 天数据）跑出报告，verdict 为
   `insufficient_data` 且指标与手工核对一致；
2. 四类 verdict 测试全绿，全量回归不退化；
3. 报告文件与 .gitignore 例外一并 commit。
