# gator-pattern-evolution Skill 与增量规则写回设计

日期：2026-11-14  
状态：方案、名称与书面设计已经用户确认；实施计划阶段补充主库 claim 格式兼容  
前置方案：`docs/design/gator-pattern-evolution-design.md`

## 一、背景与决定

仓库已有两类鳄鱼体系资产：

1. `sources/third_party/gator-method/03-规则体系/` 是第三方 55 章编号的提炼镜像，其中部分章节受限；该目录明确只读。
2. `framework/reasoning-patterns-gator.yaml` 是 Agent 实际加载的本地机读规则库，目前已含第 56 章，共 51 条 pattern。

现有 `scripts/evolve_gator_patterns.py` 已完成增量 claims 筛选、候选章节召回、LLM 五分类和周报，但仍处于 P2 影子模式：只分类，不审核写回。`processed_claim_ids` 只表示“已分类”，不代表“已人工复核”或“已沉淀到规则库”，因此当前流程可能让观点在后续周报中消失，却仍停留在待处理状态。

实施计划前的实数核查还发现了输入漏读：当前加载器只处理 list 或 `claims` 容器中的 `school: gator`，忽略主库大量“单 claim dict + `up_id=gator-ecyu-0001`”文件。原口径仅见 49 条，兼容单 claim 和 up_id 后可见 212 条，且最新已到 2026-11-12。这解释了后续周报为何错误地持续显示零新增。输入兼容是实施的首个修复，不是新增一套提取器。

第 56 章还暴露了所有权问题：其 YAML `source_path` 指向第三方目录，但该 Markdown 已在后续上游覆盖中删除。后续增量不能再写入第三方镜像。

本设计采用用户确认的第二种方案：新增一个不带 `qing` 前缀的薄编排 Skill，正式命名为 **`gator-pattern-evolution`**，复用现有 claims 和五分类管线，补齐主库输入兼容、人工审批、待复核积压追踪、P4 写回和验收。

## 二、目标与非目标

### 目标

1. 将后续鳄鱼原文中的增量观点持续归并为既有规则的新证据、条件细化、内部漂移或新主题。
2. 复用现有 `qing-learning-claim` 提取门禁和 `evolve_gator_patterns.py` 五分类，不另造提取管线。
3. 建立“待分类 → 待复核 → 已批准 → 已写回/已关闭”的可追踪闭环。
4. 所有规则变更均有原文证据、用户批准、版本日志和可重复执行保障。
5. 将第三方基线与本地演进分离，修复第 56 章失效来源，不修改上游镜像。
6. 让 Skill 可被“更新鳄鱼交易体系、鳄鱼增量、鳄鱼规则演进、gator pattern evolution、添砖加瓦”等说法稳定触发。

### 非目标

1. 不从零重提炼 55 章，不重写现有 claim 提取器或 embedding 分类器。
2. 不让 LLM 自动修改规则，不自动裁决学派内矛盾。
3. 不输出无条件买卖指令，不接交易接口。
4. 不在 `sources/third_party/gator-method/` 中新增或修改章节。
5. 不维护第二份手工同步的 55 章 Markdown 副本；本期以 YAML、提案和周报作为可追溯交付物。
6. 不因规则写回自动宣称规则经过市场验证，不自动提交或推送 Git。

## 三、数据所有权与状态定义

### 3.1 数据所有权

| 数据 | 角色 | 写入规则 |
|---|---|---|
| `sources/third_party/gator-method/` | 第三方基线镜像 | 只读；仅独立的上游同步任务可覆盖 |
| `knowledge/claims/claim-*.yaml` | 原文观点与证据层 | 沿用现有提取门禁；鳄鱼身份由 `school: gator` 或主库 `up_id=gator-ecyu-0001` 确认 |
| `framework/reasoning-patterns-gator.yaml` | 本地持续演进的唯一规则主库 | 只能由批准的 P4 提案通过写回器修改 |
| `framework/proposals/YYYYMMDD-gator-*.yaml` | 人工复核与批准凭证 | 先生成待审提案，用户明确批准后才能执行 |
| `infra/data/gator_pattern_evolution/state.json` | 分类与复核状态 | 保留现有字段，新增复核状态，不把已分类等同于已写回 |
| `reports/gator-pattern-evolution-*.md` | 分类和人工复核材料 | 可由管线生成，不是规则主库 |

`framework/reasoning-patterns-gator.yaml` 顶部的 `generated_by` 和 `generated_at` 保留为初始导入历史；后续批次更新 `version`、`updated_at` 和 `evolution_log`。日常增量禁止再用 `build_gator_patterns.py` 全量重建覆盖本地演进。

基础 pattern 可继续保留指向现存第三方章节的 `source_path`。本地新增或演进部分使用 `source_claims` 追溯真实 claims；不得为本地新增内容虚构第三方来源路径。

### 3.2 分类状态与复核状态分离

现有 `processed_claim_ids` 和 `classifications` 原样保留，新增：

```yaml
review_status:
  claim-20261021-008-c:
    status: observing
    proposal_id: 20261114-gator-example
    updated_at: '2026-11-14T00:00:00+08:00'
    note: 单源新主题，等待不同日期证据
```

实际状态文件仍为 JSON，上例仅表示字段结构。允许的状态为：

- 缺省或 `pending-review`：已分类，仍需人工复核；不能从待办中消失。
- `observing`：单源新主题或证据不足，等待后续不同日期观点；不是终态。
- `applied`：批准内容已写回规则库，或矛盾漂移已登记。
- `reviewed-irrelevant`：人工确认与规则层无关，关闭且不改规则。
- `rejected`：人工否定该归类或写回建议，记录理由并关闭。

`parse_error`、缺少原文、未知 claim、未知 pattern、孤立 state 记录都必须显式报告，不能静默算作完成。

## 四、总体架构

```text
鳄鱼新文章/视频
  → 现有 claim 提取与门禁（必要时执行）
  → 新增 claims 时执行 discover → Neo4j → Qdrant → Agent 重载
  → evolve_gator_patterns.py：增量筛选 + top-3 召回 + LLM 五分类
  → gator-pattern-evolution Skill：汇总本周新增 + 历史待复核 backlog + 未解决漂移
  → 对照 claim 原文和完整目标 pattern 人工复核
  → framework/proposals/ 中的待审提案
  → 用户明确批准
  → apply_gator_pattern_evolution.py --dry-run：完整校验与 diff 预览
  → 用户要求执行写回
  → P4 写回器：规则 YAML + state.json + 提案状态
  → 引用/结构/路由测试，必要时重启 Agent 清缓存
```

Skill 是编排与判断层，不复制脚本逻辑。P4 写回器是机械执行层，不做语义裁决。

## 五、Skill 职责与停止条件

### 5.1 主 Skill

新建 `skills/gator-pattern-evolution/SKILL.md`，只包含：

- 触发词、适用边界和现有资产位置；
- 预检查、分类、待复核 backlog、提案、审批、写回、验收的执行顺序；
- 五类写回规则及禁止事项；
- 常用命令和失败时停止条件；
- 指向详细参考文件的链接。

### 5.2 详细参考

新建 `skills/gator-pattern-evolution/references/review-and-writeback.md`，承载：

- 提案字段契约和各类 decision 示例；
- 原文保真复核清单；
- 允许修改的 pattern 字段；
- 幂等、版本、状态和异常处理规则；
- 第 56 章这类本地演进 pattern 的来源标注规范。

### 5.3 必须停止的情况

出现以下任一情况时，Skill 不得直接写规则：

- claim 同时缺 `school: gator` 和 `up_id=gator-ecyu-0001`，或缺原文路径、`evidence_quote`；
- 仅看到 LLM 分类，没有人工复核；
- `refine` 没有原规则条款与新原文的双侧证据；
- `contradict` 被要求自动判断谁对谁错；
- `new_theme` 少于两个不同 `source_date`；
- 提案不是 `status: approved`，或当前对话没有用户明确批准/执行指令；
- dry-run 出现未知引用、证据不一致或非法字段修改。

## 六、人工复核与提案契约

### 6.1 复核范围

每次运行同时处理：

1. 本周新分类 claims；
2. `classifications` 中仍无终态的历史 backlog；
3. 规则库中 `resolution: pending` 的漂移项；登记 drift 的 claim 可以关闭，但未解决漂移仍须单独出现在待办中；
4. state 中存在、当前 gator claims 中已找不到的孤立记录，单独列为异常，不自动丢弃。

复核者必须读取 claim 的 `evidence_quote` 和完整目标 pattern，而不是只看 top-3 相似度或 LLM 的摘要。候选均不匹配时允许人工改判；LLM 分类不是审批结论。

### 6.2 提案结构

提案使用 `framework/proposals/YYYYMMDD-gator-<topic>.yaml`，至少包含：

```yaml
proposal_id: 20261114-gator-bottom-cycle
school: gator
status: pending-review
source_report: reports/gator-pattern-evolution-20261022.md
generated_at: '2026-11-14T00:00:00+08:00'
approved_by: null
approved_at: null
decisions:
  - action: reinforce
    claim_id: claim-20261021-008-c
    pattern_id: gator-ch56-2026-10-16-10-22
    rationale: 新文章补充护盘弹药管理证据
    evidence_quote: 原文逐字引文
```

执行前必须由用户批准，并将 `status` 改为 `approved`，填写 `approved_by` 和 `approved_at`。Agent 不得自行伪造批准字段。

`new_theme` decision 使用 `claim_ids` 列表和 `candidate_pattern`。候选内容必须包含 `slug/name/description/trigger/steps/thresholds/table_rules/falsification/computable/core/validation`；`slug` 只用于生成 ID，不写入 pattern。`pattern_id/chapter/school/provenance` 由写回器生成，`source_claims/source_dates` 由写回器从 claims 派生，避免审批文本与机械字段不一致。写回器验证这些 claims 至少覆盖两个不同来源日期。`refine` decision 使用 `set` 明确给出修改后的完整字段值，禁止只写自然语言修改意图。

## 七、五类写回动作

| 分类 | 批准后的机械动作 | 禁止事项 |
|---|---|---|
| `reinforce` | 向 pattern 的 `source_claims` 追加去重 claim ID；合并并排序 `source_dates`；更新 `local_evidence_count` | 不改触发条件，不把重复确认当市场命中率 |
| `refine` | 替换提案明确列出的字段，附 `source_claims`、来源日期和前后 diff 日志 | 只能改 `description/trigger/steps/thresholds/table_rules/falsification`，不得改 ID、章节、学派或 validation |
| `contradict` | 向 `drift_flag` 列表追加记录，包含 claim、冲突原文和 `resolution: pending` | 不改原决策字段，不自动 supersede，不选择胜负 |
| `new_theme` | 达到多日期门槛后新增完整 pattern，章节号取当前最大章节号加一，生成对应 `gator-chNN-*` ID | 不回填受限缺章，不接受单源直接入库，不复制第三方 provenance |
| `irrelevant` | 仅将复核状态置为 `reviewed-irrelevant` | 不改规则 YAML，不递增规则版本 |

人工否决使用 `rejected`，证据不足使用 `observing`。后续解决矛盾必须另提明确的修订提案；登记 `drift_flag` 不等于冲突已经解决。

另设仅用于来源迁移的 `repair_provenance` decision，不改变五分类语义。它只在现有 `source_path` 已失效时可用，必须附可核实的 `claim_ids` 和 `reason: broken-source-path`；动作仅删除失效路径、写入本地 provenance 和派生证据字段，不得借修复修改任何规则内容。第 56 章通过这一动作执行，避免用普通 `refine` 绕过 provenance 白名单。

`local_evidence_count` 始终等于去重后的 `source_claims` 数量，由写回器派生，不能手工填写。它只表示本项目已关联的原文观点数量，不表示第三方原始文章总数，也不表示策略有效性。

每个有实际规则变化的批次只递增一次版本，并追加一条顶层 `evolution_log`，记录 `proposal_id`、批准人、动作、claim IDs 和前后差异。纯状态关闭不递增规则版本。

## 八、P4 写回器与文件边界

### 8.1 文件职责

- 新建 `src/investment_engine/pattern_eval/gator_evolution.py`：提案校验、待复核查询、五类变更、幂等守卫、版本日志和原子写回。
- 新建 `scripts/apply_gator_pattern_evolution.py`：薄 CLI 包装，复用现有脚本的命令行习惯。
- 新建 `tests/test_gator_pattern_evolution_apply.py`：真实数据结构与临时目录上的单元/集成测试。
- 修改 `tests/test_pattern_prompt_policy.py:230`：把固定“总数必须为 51”改为“既有 51 个 ID 不丢失且顺序保持，允许批准后新增”，避免合法演进被旧基线误伤。
- 修改 `scripts/evolve_gator_patterns.py`：仅在必要时共享数据读取函数，不改变现有五分类语义。
- 修改 `docs/design/gator-pattern-evolution-design.md`：标注 P4 设计已由本 Skill 方案承接，避免文档状态冲突。
- 修改 `framework/reasoning-patterns-gator.yaml`：仅执行批准提案和本设计规定的第 56 章来源修复。
- 修改 `infra/data/gator_pattern_evolution/state.json`：仅在真实运行时追加复核状态，不在测试或 dry-run 中改写。

不修改 `src/qing_investment/agent/graph/nodes.py`；现有加载器已经读取 gator YAML。写回后如需让长驻进程使用新版本，按既有缓存纪律重启 Agent。

### 8.2 CLI

```bash
# 查看已分类但未关闭的 backlog、未解决漂移和孤立记录
.venv/bin/python scripts/apply_gator_pattern_evolution.py --list-pending

# 预览批准提案；不得修改 YAML、state 或提案
.venv/bin/python scripts/apply_gator_pattern_evolution.py \
  framework/proposals/YYYYMMDD-gator-topic.yaml --dry-run

# 用户明确要求执行后才写回
.venv/bin/python scripts/apply_gator_pattern_evolution.py \
  framework/proposals/YYYYMMDD-gator-topic.yaml
```

默认规则库为 `framework/reasoning-patterns-gator.yaml`，默认状态文件为现有 `infra/data/gator_pattern_evolution/state.json`。测试必须显式传入临时文件，禁止污染生产数据。

### 8.3 校验与原子性

1. 先校验所有 decisions、claim/pattern 引用、来源日期、证据引文和字段白名单；任一失败则整批拒绝，不部分写规则。
2. 使用 `ruamel.yaml` round-trip 保留未触碰部分的格式；所有校验通过后才写临时文件并原子替换。
3. dry-run 输出逐 decision diff 和状态变化，规则 YAML、state、提案的字节内容保持不变。
4. 规则写成功后更新 state 和提案的执行信息；提案 `applied` 表示本批复核决定已处理，不表示每条 decision 都修改了规则。若后续更新失败，重跑依靠幂等守卫修复状态，不重复改规则。
5. 相同 claim、action、pattern 的 decision 重放不得重复追加证据、漂移记录、章节或日志。
6. 不直接复用 qing 的 `validate_patterns_file`：该 schema 要求 gator 当前没有的 `data_requirements` 和结构化 steps。P4 使用独立的 gator 完整性校验，同时保留既有 `validation` 区块不变。

## 九、第 56 章一次性修复

1. 从现有 claims、2026-10-22 周报和第 56 章 `evolution_log` 核对真实证据，展开 `claim-20261016-004/005` 等文件级简写为实际带后缀的 claim IDs；无法核实的不得填入。
2. 删除失效的第三方 `source_path`，将 provenance 改为本地鳄鱼规则演进来源，并填入核实后的 `source_claims`、来源日期和 raw 路径。
3. 保留第 56 章既有规则内容和用户 2026-10-22 的批准记录，不借来源修复重新进行语义改写。
4. 在 `evolution_log` 追加一次来源修复记录，不伪造成第三方上游章节。
5. 历史每日 wiki 中“当时已写入第三方目录”的记录作为历史事实保留；修复报告说明该来源已迁移到本地规则库，避免改写历史。

修复后，所有非空 `source_path` 必须指向现存文件；所有本地演进 pattern 必须至少有一个可解析的 `source_claims` 证据。

## 十、异常与缺失处理

- **本周无新增**：仍检查 backlog；只有新增和 backlog 均为空时才报告“无待处理”。
- **LLM 失败或 parse_error**：保留待复核，不生成可执行写回 decision。
- **claim/state 孤立记录**：单独报告数量和 ID；相关 decision 整批拒绝，不静默删除历史状态。
- **原文引文不匹配**：退回 claim 层修正，不能靠改写引文通过规则写回。
- **单源新主题**：标记 `observing`，后续同主题不同日期证据到达后再提案。
- **矛盾**：只登记并展示双方证据，不自动改旧规则。
- **长驻 Agent 缓存**：文件更新不等于运行进程已加载，验收时明确检查是否需要重启。

## 十一、测试与 Skill 验证

### 11.1 写回器测试

先写失败测试，再实现最小代码，至少覆盖：

1. 未批准提案拒绝执行；dry-run 三个文件均不变。
2. 未知 claim/pattern、失效 source_path、错误证据、非法字段均整批拒绝。
3. `reinforce` 证据与日期去重，重复执行结果一致。
4. `refine` 只修改白名单字段，版本和 evolution_log 每批只增加一次。
5. `contradict` 只追加 drift，不修改 trigger/thresholds，不自动裁决。
6. 单源 `new_theme` 拒绝入库；多日期新主题生成连续章节号，重复提案不重复建章。
7. `irrelevant/rejected/observing` 只更新复核状态，不改规则版本。
8. 已分类但无复核终态的 claim 出现在 backlog；已关闭项不再出现；未解决 drift 持续出现；孤立记录单独报告。
9. state 或提案更新失败后重放不产生重复规则变更。
10. 第 56 章修复后的来源和 claims 引用可解析，现有 51 条 pattern 的 ID、顺序和 validation 不被意外改变。
11. 现有路由测试保留既有 51 个 ID 的防回归断言，同时允许新增合法 pattern，不再要求总数永远等于 51。

### 11.2 Skill 行为验证

按 `writing-skills` 的 RED-GREEN-REFACTOR 方式，用压力场景比较无 Skill 与有 Skill 的 Agent：

1. 给定一条已分类 reinforce，检查是否只会停在周报，或误改第三方目录。
2. 给定 refine/contradict，检查是否绕过用户审批或自动裁决。
3. 给定单源 new_theme，检查是否直接创建新章。
4. 给定“本周新增为 0 但 backlog 非空”，检查是否错误报告全部完成。
5. 给定第 56 章失效路径，检查是否伪造或恢复上游文件来掩盖问题。

有 Skill 后必须表现为：复用现有管线、先列 backlog、生成提案、等待批准、dry-run、批准后才写回，并保留完整证据链。

### 11.3 端到端验收

使用 2026-10-22 历史周报构造提案，并仅在临时文件中标记测试批准，在临时规则库和临时 state 上完成一次 reinforce、一次 refine、一次单源观察、一次矛盾登记和一次 irrelevant 关闭；随后对生产文件执行只读 `--list-pending` 和批准提案的 dry-run。没有用户对真实提案的单独执行指令，不把测试内容写入生产规则库。

项目现有相关测试，包括 gator pattern 路由、pattern prompt policy 和监控规则测试，必须保持通过。最终再运行项目标准测试命令；若全量测试存在与本次无关的既有失败，须明确区分并报告，不能宣称全绿。

## 十二、实施阶段与文件清单

### Phase 1：机械写回与状态闭环

- 新建 `src/investment_engine/pattern_eval/gator_evolution.py`
- 新建 `scripts/apply_gator_pattern_evolution.py`
- 新建 `tests/test_gator_pattern_evolution_apply.py`
- 修改 `tests/test_pattern_prompt_policy.py` 的固定数量基线
- 必要时小幅修改 `scripts/evolve_gator_patterns.py` 以复用读取逻辑

### Phase 2：第 56 章来源修复

- 修改 `framework/reasoning-patterns-gator.yaml`
- 生成对应修复提案和 dry-run/执行记录
- 只在用户批准该真实提案后写生产 YAML 和 state

### Phase 3：Skill 与文档

- 新建 `skills/gator-pattern-evolution/SKILL.md`
- 新建 `skills/gator-pattern-evolution/references/review-and-writeback.md`
- 修改 `docs/design/gator-pattern-evolution-design.md`
- 按 Skill 行为场景完成 baseline、加载后复测和缺陷修正

### Phase 4：整体验证

- 运行新增测试和现有 gator 相关测试
- 执行临时副本端到端验收
- 对生产文件做只读 backlog/dry-run 验证
- 检查所有新增文档、命令和实际行为一致

## 十三、完成标准

只有同时满足以下条件才算完成：

1. `gator-pattern-evolution` 能被目标触发词发现，且不依赖名称中带 `qing` 的入口。
2. 新观点从 claim 到分类、复核、批准、写回或关闭均有可查询状态，backlog 不会因周报运行而丢失，未解决漂移也不会从待办中消失。
3. 五类决策按本设计执行，所有实际规则变化都有用户批准、原文证据和版本日志。
4. dry-run 无副作用，重复执行幂等，失败不会留下部分规则变更。
5. 第三方目录保持只读，第 56 章失效来源被修复，本地规则证据链可解析。
6. 新 Skill 通过压力场景验证，新增测试与现有 gator 相关测试通过。
7. 真实生产规则写回仍有独立用户批准；本设计和测试本身不冒充已经完成增量规则沉淀。
