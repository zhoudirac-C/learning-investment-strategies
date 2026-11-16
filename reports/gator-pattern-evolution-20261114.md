# gator pattern 演进周报（2026-11-14）

> 阶段：P2 影子模式（LLM 五分类已接入，hermes_global（fallback: openrouter/workbuddy/sensenova））
> 窗口：自 2026-11-13（显式指定） ｜ gator claims 总数：221 ｜ 本周新增：2
> ⚠️ 影子期约束：本报告不改任何 framework yaml，所有归类需人工复核；contradict/refine 不自动裁决。

## 一、五分类汇总

| 类别 | 数量 | 含义 |
|---|---|---|
| reinforce | 0 | 新例证强化既有规则 |
| refine | 0 | 阈值/条件修正（需人审） |
| contradict | 0 | 学派内漂移（需人审，不自动裁决） |
| new_theme | 1 | 规则库未覆盖新主题 |
| irrelevant | 1 | 与规则层无关 |
| parse_error | 0 | LLM 解析失败（需人审） |

## 四、🆕 new_theme（1 条）

### 主题聚合（D4：≥2 个来源日期 → 可进 framework/proposals/）

- **高股息/ 行为风险**（1 条，1 个日期：2026-11-13）

### claim-20261113-009（2026-11-13）
- **topic**: 高股息/ 行为风险
- **statement**: 很多刚开始做高股息的选手，真的会因为市场的诱惑和这些言论而半途而废。
- **分类**: `new_theme` → `无`
- **理由**: claim 关注高股息投资者因市场诱惑与噪音半途而废的行为风险；三个候选分别涉空仓防御、基本面顶底、技术/规则杀，均未覆盖策略执行的心理坚持层面，相似度主要来自“高股息”关键词，故判新主题。
- **候选 pattern（top-3）**:
  0.862 第29章 短线顶级防御：空仓与现金为王（`gator-ch29-shortterm-cash-defense`）
  0.825 第22章 基本面框架：短期驱动与长期定价（`gator-ch22-fundamental-framework`）
  0.824 第25章 三种杀与防御（`gator-ch25-three-kills-defense`）

## 六、irrelevant（与规则层无关）（1 条）

### claim-20261113-008（2026-11-13）
- **topic**: 缩量杀跌/ 盘面归因
- **statement**: 今天下午这种缩量的杀跌，不用怀疑，又有很多地方开始通知割肉了。
- **分类**: `irrelevant` → `无`
- **理由**: claim 主为当日盘面描述与情绪归因，未对规则进行确认、修正或提出新主题，属行情描述/情绪吐槽。
- **候选 pattern（top-3）**:
  0.796 第15章 反例规则：什么"看起来像见底"但不是（`gator-ch15-false-bottom-rules`）
  0.779 第14章 下跌幅度与左侧买入（`gator-ch14-decline-depth-left-buy`）
  0.776 第39章 抱团瓦解与牛市终结（`gator-ch39-herd-collapse-bull-end`）

## 人工复核区（2026-11-14 原文与完整 pattern 对照）

已逐条复核 001–009 的原文、claim evidence_quote 和候选之外的完整相关 pattern。top-3 漏召回不构成新增主题的理由；下述人工认定均未写入规则主库。

| claim_id | LLM 归类 | 人工认定 | 目标 pattern | 处置 |
|---|---|---|---|---|
| claim-20261113-001 | new_theme | reinforce（已写回） | gator-ch10-bull-4-taboos | 新日期行为例证，不得扩成永不止损 |
| claim-20261113-002 | irrelevant | observing（已记录） | 无 | 主观机制解释，不转成反向跟单规则 |
| claim-20261113-003 | new_theme | refine（已写回） | gator-ch06-long-short-response | 补非短线建仓后纪律，保留计划退出条件 |
| claim-20261113-004 | irrelevant | reinforce（已写回） | gator-ch45-index-sector-mismatch | 窄龙头替代全市场判断的例证 |
| claim-20261113-005 | new_theme | refine（待审） | gator-ch56-2026-10-16-10-22 | 澄清早期右侧与保守重仓确认范围 |
| claim-20261113-006 | new_theme | refine（已写回） | gator-ch26-ta-core-thresholds | 不得仅凭填坑确认反转，不编量化阈值 |
| claim-20261113-007 | new_theme | refine（已写回） | gator-ch43-emotion-rhythm-3-waves | 补等B浪和空间、不追空的定性步骤 |
| claim-20261113-008 | irrelevant | reviewed-irrelevant（已关闭） | 无 | 规则层关闭，保留市场快照价值 |
| claim-20261113-009 | new_theme | reinforce（已写回） | gator-ch18-trading-system-3-investors | 高股息持有纪律的行为风险例证 |

提案与审批状态：

- `framework/proposals/20261114-gator-20261113-review.yaml` 已写回，状态为 `applied`：001、004、009 reinforce；003、006、007 refine；002 observing；008 irrelevant。006已按审批意见改为“不得仅凭填坑确认趋势反转”。
- `framework/proposals/20261115-gator-right-side-scope.yaml` 仍为待审：`claim-20261026-019` 澄清融资组合是保守重仓的充分确认而非早期右侧必要条件，005补平均股价指数与市场结构维度；不再登记contradict。
- `framework/proposals/20261114-gator-ch56-provenance-repair.yaml` 已写回，状态为 `applied`：失效第三方source_path已移除并关联14个真实claim，第56章语义字段未变，state与生产规则的来源状态已一致。

证据边界：

- 003 的“不追不割”以非短线、逻辑未失效、仓位成本受控为前提，既有止损、止盈和时间上限继续有效。
- 006 只禁止仅凭填坑确认趋势反转，不限制填坑完成前出现右侧或趋势改善；尚无统一的坑起点和完成阈值。
- 007 只增加定性做空步骤，“多头重新聚集”和“空间出来”尚无可观测量化门槛。
- 第56章现有AND组合可视为保守确认的充分条件，与“早期右侧不必然等待两融”并不构成逻辑矛盾；右侧范围提案若获批准，trigger与thresholds必须同步澄清范围。
- 高股息长期吃息体系与安全垫已有11月4日、11月9日跨日期材料，可另做去重评审；009本身不是新主题，本批不提交new_theme。

当前规则版本为 `1.3-draft`。一般提案与来源修复提案均已通过生产dry-run、字段级写后校验和重放幂等检查；右侧范围提案未写回。写回器位于 `src/investment_engine/pattern_eval/gator_evolution.py`，CLI为 `scripts/apply_gator_pattern_evolution.py`。

写回验收：16项写回器测试及51项相关回归测试共67项通过；完整测试为2426 passed、4 skipped、5 deselected。51个pattern的来源路径和证据计数均已实查，Agent已重启并通过 `/health` 检查。

---
*embedding: onnx-bge-small-zh（或 fallback-hash，见日志） ｜ LLM: hermes_global（fallback: openrouter/workbuddy/sensenova） ｜ 生成: scripts/evolve_gator_patterns.py*
