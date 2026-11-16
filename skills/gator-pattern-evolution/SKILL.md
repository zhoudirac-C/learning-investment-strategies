---
name: gator-pattern-evolution
description: Use when 更新鳄鱼交易体系、处理鳄鱼增量、复核鳄鱼规则周报、写回 gator patterns、推进规则演进，或给55章鳄鱼体系添砖加瓦。
---

# Gator Pattern Evolution

## 目标

把后续鳄鱼观点沉淀到本地规则库，复用现有 claim 与五分类。55 章第三方内容是只读基线：不重新提炼 55 章，不直接修改第三方镜像。

## 资产与边界

| 资产 | 路径 | 用途与边界 |
|---|---|---|
| 第三方镜像 | `sources/third_party/gator-method/` | 只读；不得编辑或恢复同名上游文件 |
| 规则主库 | `framework/reasoning-patterns-gator.yaml` | 本地规则唯一写回目标 |
| 演进状态 | `infra/data/gator_pattern_evolution/state.json` | 分类、processed 与复核状态；processed 不等于已复核 |
| 提案 | `framework/proposals/` | 待审、批准与执行记录 |
| 分类器 | `scripts/evolve_gator_patterns.py` | 只做增量筛选、候选召回、五分类与报告，不做复核写回 |
| 复核写回器 | `scripts/apply_gator_pattern_evolution.py` | 查询待办、校验提案、dry-run 与正式写回 |

## 执行顺序

1. 新增 claim 先走现有提取门禁，再完成 discover → Neo4j migrate → Qdrant rebuild → Agent 重载；不得为规则演进绕过知识管线。
2. 用分类器完成五分类后，必须运行 `.venv/bin/python scripts/apply_gator_pattern_evolution.py --list-pending`。分类结果不是人工复核结论。
3. 核查并分流 `pending_review`、`unclassified_claim_ids`、`orphan_claim_ids`、`unresolved_drifts`；pending drift 只核查、登记并保持在 backlog，不在本轮复核中关闭。零新增不等于零待办，processed 不等于已复核。
4. 逐条阅读 claim 的 `evidence_quote`、`source_path` 指向的 raw 原文及目标完整 pattern；不得只凭周报摘要或相似度决定。
5. 在 `framework/proposals/` 生成 `status: pending-review` 的待审提案，字段与决策契约见 [复核与写回参考](references/review-and-writeback.md)。
6. 只有用户明确批准，才能把状态改为 `approved` 并填写真实的 `approved_by`、`approved_at`。批准不等于授权执行。
7. 对已批准提案先 dry-run，展示规则库、状态、提案三文件 diff；发现校验错误则停止，不落盘。
8. 只有用户在当前对话明确要求执行，才去掉 `--dry-run` 正式写回。随后运行相关测试，核查证据与各类待办去向，不把减少 `unresolved_drifts` 作为目标；规则检索内容变化时按需重启 Agent。

## 五类动作

| 动作 | 允许结果 |
|---|---|
| `reinforce` | 仅补充真实 claim 证据、日期与 raw 来源，不改规则语义 |
| `refine` | 仅改 `description/trigger/steps/thresholds/table_rules/falsification`，必须有双侧引文并展示前后 diff |
| `contradict` | 仅登记 `resolution: pending` 的 drift，不裁决、不改写原规则 |
| `new_theme` | 使用 `claim_ids + candidate_pattern`，至少覆盖两个不同 `source_date`，candidate 契约不得缺项或多项 |
| `irrelevant` | 仅将复核状态关闭为 `reviewed-irrelevant`，不改 pattern |

`rejected` 与 `observing` 必须填写非空 `note`。`observing` 不是终态，会继续留在待办；写明观察原因不代表证据已经入库，也不代表已新增规则。

## 停止条件

出现以下任一情况，停止并说明缺口，不得猜测或自动补全：

- 缺 claim/pattern 身份、raw 原文或 `evidence_quote`。
- 只有 LLM 分类，没有逐条人工复核；或要求自动裁决矛盾。
- `refine` 缺 claim 侧或 pattern 侧证据；`new_theme` 只有一个来源日期。
- 提案未获批准，或当前对话没有明确的执行授权。
- dry-run 报未知引用、失效路径（经批准的 `repair_provenance` 目标除外）或非法字段。
- 要求修改第三方镜像或恢复同名上游文件。

ch56 的失效来源只能用 `repair_provenance` 修复为真实本地 provenance；禁止 `git restore` 第三方文件，禁止虚构替代路径，禁止借修复改变规则语义。

## 异常处理

- `unclassified`：先补有效五分类，再复核；不得直接写回。
- `orphan`：不得按文件茎猜测映射，也不得删除 state；先恢复历史实体或核实引用，无法确认则停止。
- 重复 claim ID 或 pattern ID：立即停止，先消除身份冲突。
- drift 与待复核分开核查、分流：`contradict` 成功可减少对应 claim 的 `pending_review`，但不会减少 `unresolved_drifts`，pending drift 必须保持在 backlog。drift 解决需另提案；当前没有自动关闭 drift 的 action。
