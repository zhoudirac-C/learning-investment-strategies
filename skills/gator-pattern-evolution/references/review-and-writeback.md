# 复核与写回契约

所有命令从仓库根目录运行。分类器只生成候选分类与报告；提案复核、dry-run 和写回统一使用 `scripts/apply_gator_pattern_evolution.py`。

## 提案顶层字段

| 字段 | 契约 |
|---|---|
| `proposal_id` | 非空、唯一，与提案文件对应 |
| `school` | 必须为 `gator` |
| `status` | 新建为 `pending-review`；用户明确批准后改为 `approved`；成功执行后为 `applied` |
| `source_report` | 真实分类周报路径 |
| `generated_at` | 真实生成时间，ISO 8601 格式 |
| `approved_by` | 待审时为 `null`；批准后填写真实批准者，不得预填 |
| `approved_at` | 待审时为 `null`；批准后填写真实批准时间，不得预填 |
| `decisions` | 非空 decision 列表，逐条对应人工复核结论 |

可记录真实用户授权依据，例如当前对话中的批准原话与时间；不得伪造授权依据，也不得以其替代 `status: approved`、`approved_by` 或 `approved_at`。

执行器成功写回后记录：

- `status: applied`
- `applied_at`：真实执行时间。
- `applied_pattern_version`：本次执行对应的规则版本；幂等重放必须保留历史值，不得伪造新版本。

dry-run 也执行批准校验，因此只有 `approved` 提案可进入 dry-run；`applied` 仅用于幂等重放。批准提案与授权正式执行是两个独立动作。

## Decision 字段

通用单 claim decision 的人审契约使用：

```yaml
action: reinforce        # 或 refine/contradict/irrelevant/rejected/observing
claim_id: claim-YYYYMMDD-NNN-x
evidence_quote: claim 原文中的连续子串
```

上述 `action/claim_id/evidence_quote` 是人审通用单 claim 字段。状态动作 `irrelevant/rejected/observing` 仍应记录 `evidence_quote` 供人审，但执行器不强制要求或校验该字段；执行器仅对 `reinforce/refine/contradict` 强制校验其非空且为对应 claim `evidence_quote` 的子串。

- `reinforce/refine/contradict` 另填 `pattern_id`，必须引用主库已有 pattern。
- `refine/contradict` 另填 `conflict_quote`，必须是目标完整 pattern 原文中的子串。
- `refine` 另填非空 `set`，仅包含允许的修改字段。
- `rejected/observing` 另填非空 `note`；`irrelevant` 可用 `note` 说明关闭原因。
- `rationale` 可记录人工复核理由，但不能替代原文、双侧引文或用户授权。

各动作契约：

| `action` | 人审契约字段 | 写回语义 |
|---|---|---|
| `reinforce` | 通用字段 + `pattern_id` | 仅增加去重后的证据、来源日期与 raw 来源 |
| `refine` | 通用字段 + `pattern_id/conflict_quote/set` | 增加证据并修改白名单字段，保留前后 diff |
| `contradict` | 通用字段 + `pattern_id/conflict_quote` | 只追加 `resolution: pending` 的 drift，不裁决 |
| `irrelevant` | 通用字段 | 仅写 `reviewed-irrelevant` 复核状态 |
| `rejected` | 通用字段 + `note` | 仅写 `rejected` 复核状态 |
| `observing` | 通用字段 + `note` | 仅写非终态 `observing`，继续出现在待复核 backlog |
| `new_theme` | `action/claim_ids/candidate_pattern` | 新增本地 pattern 并关联全部真实证据 |
| `repair_provenance` | `action/pattern_id/claim_ids/reason/provenance` | 仅修复失效来源与本地证据，不改语义 |

### `refine` 白名单

`set` 只允许以下六个字段，不多不少地按实际修改项填写：

- `description`
- `trigger`
- `steps`
- `thresholds`
- `table_rules`
- `falsification`

禁止通过 `set` 修改 `pattern_id` 或其他 ID、`chapter`、`school`、`validation`。`evidence_quote` 与 `conflict_quote` 必须分别命中 claim 和修改前目标 pattern 的原文；dry-run 必须展示可审阅的前后 diff。

### `new_theme`

使用 `claim_ids`，不得用单 claim 形式代替。所有 claim 必须真实存在、具有有效原文与证据，并覆盖至少两个不同的 `source_date`；单源新主题停止写回，可保留为带原因的非终态 `observing`，不得包装成 `new_theme`。

`candidate_pattern` 字段必须精确为以下 11 项，不得缺项或增加字段：

```yaml
candidate_pattern:
  slug: kebab-case-slug
  name: ...
  description: ...
  trigger: ...
  steps: ...
  thresholds: ...
  table_rules: ...
  falsification: ...
  computable: ...
  core: ...
  validation: ...
```

`slug` 使用 kebab-case。`pattern_id/chapter/school/provenance` 等由写回器生成或登记，不得塞入 candidate。只有分类结果、没有完整 candidate 或跨日期证据时，不得提交写回。

### `repair_provenance`

```yaml
action: repair_provenance
pattern_id: gator-ch56-2026-10-16-10-22
claim_ids:
  - claim-真实存在且已核实的ID
reason: broken-source-path
provenance: local-gator-evolution（仅修复失效来源）
```

该动作只用于当前 `source_path` 已失效的本地演进 pattern：移除失效来源，写入以 `local-gator-evolution` 开头的真实本地 provenance，并补充真实 claim 证据。不得修改 `description/trigger/steps/thresholds/table_rules/falsification/validation` 等语义内容。

ch56 不得通过修改第三方镜像、恢复同名上游文件或 `git restore` 修复；不得虚构替代路径。无法以真实本地 claim 和 provenance 闭环时停止。

## 复核状态映射

| 成功 decision | `review_status.status` | 是否终态 |
|---|---|---|
| `irrelevant` | `reviewed-irrelevant` | 是 |
| `rejected` | `rejected` | 是，且必须有 `note` |
| `observing` | `observing` | 否，必须有 `note`，继续待办 |
| `reinforce/refine/contradict/new_theme/repair_provenance` | `applied` | 是 |

`applied` 只表示 decision 已处理，不表示矛盾已裁决。`contradict` 成功可减少对应 claim 的 `pending_review`，但产生的 pending drift 独立留在 `unresolved_drifts`，不会随之减少，也不得因复核状态覆盖而删除。drift 解决需另提案；当前没有自动关闭 drift 的 action。

## 命令

分类并生成周报：

```bash
.venv/bin/python scripts/evolve_gator_patterns.py --window 7d
```

分类后查询全部待办；即使本次零新增也必须执行：

```bash
.venv/bin/python scripts/apply_gator_pattern_evolution.py --list-pending
```

以下真实 ch56 提案已经 `applied`，两条命令仅用于演示历史幂等重放，可能无 diff；不得把历史重放当作新提案会产生实际 diff 的演示。处理本次新批准提案时，必须将下面两处路径替换为本次真实提案路径。新提案仍须先获用户明确批准，再 dry-run 并展示三文件 diff：

```bash
.venv/bin/python scripts/apply_gator_pattern_evolution.py framework/proposals/20261114-gator-ch56-provenance-repair.yaml --dry-run
```

正式执行（使用上述历史文件时为幂等重放）必须以相应 dry-run 通过且用户在当前对话另行明确要求执行为前提：

```bash
.venv/bin/python scripts/apply_gator_pattern_evolution.py framework/proposals/20261114-gator-ch56-provenance-repair.yaml
```

## 验收清单

- [ ] 每条 claim 身份、`source_path` 与 raw 原文均已核实；每个非空 `source_path` 指向真实存在的文件，未虚构替代路径。
- [ ] 单 claim decision 均保留人审 `evidence_quote`；其中 `reinforce/refine/contradict` 的引文必须是对应 claim `evidence_quote` 的子串，状态动作的引文用于人审，执行器不强制校验。
- [ ] `refine/contradict` 具备双侧引文：claim 侧 `evidence_quote` 与 pattern 侧 `conflict_quote` 均命中原文。
- [ ] `new_theme` 至少覆盖两个不同 `source_date`，candidate 恰好包含规定的 11 个字段。
- [ ] dry-run 前后，规则主库、state、提案三个文件字节完全不变；diff 仅包含获批动作。
- [ ] 重放不重复新增 pattern、drift、证据或 evolution log，并保留历史 `applied_pattern_version`。
- [ ] 每个 `source_raw` 路径存在；`local_evidence_count == len(set(source_claims))`。
- [ ] pending drift 持续出现在 `--list-pending` 的 `unresolved_drifts` backlog，未被复核状态误关闭；drift 解决需另提案，当前没有自动关闭 drift 的 action。
- [ ] 每条已分类 claim 都有正确复核状态覆盖；`rejected/observing` 的 `note` 非空，`observing` 仍在 `pending_review`。
- [ ] 正式执行后再次运行 `--list-pending`，核查并分流 `pending_review/unclassified/orphan/unresolved_drifts`；`contradict` 成功只减少 `pending_review`，不减少 `unresolved_drifts`，不得为减少待办而清除 pending drift。

相关测试：

```bash
.venv/bin/python -m pytest tests/test_evolve_gator_patterns.py tests/test_gator_pattern_evolution_apply.py tests/test_pattern_prompt_policy.py
```
