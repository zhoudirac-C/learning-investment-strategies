---
name: qing-learning
description: |
  Investment knowledge management for the 青枫浦上Q (Qing) blogger content system.
  Covers the full lifecycle: ingestion (学习/消化/ingest raw content), extraction (claims → wiki → framework),
  and periodic review (qing review / 方法论复盘 / consistency audits).
  Use for any task involving blogger content — whether adding new material, updating methodologies,
  or reviewing existing claims for contradictions and drift.
---

# qing-investment-knowledge

## 目标

管理博主投资内容的完整知识生命周期：
1. **Ingestion（学习）**：持续学习博主新内容，更新 `sources`、`knowledge/claims`、`knowledge/wiki`、`methodology`、`framework` 和日志。
2. **Review（复盘）**：周期性检查 claims、wiki、methodology 和 framework，识别长期方法论变化、矛盾、过期观点和需要人工确认的问题。

## 跨 Skill 兼容性说明

> **⚠️ 关于"让AI像UP一样思考"：** 当用户询问如何蒸馏UP的思维/让AI模仿UP分析时，答案已在 `references/expert-distillation-guide.md`（三条技术路径：Prompt+RAG/Fine-tune/Agent）和 `references/reasoning-pattern-architecture.md`（三层架构：知识库→推理模式→动态应用，含YAML模板和实施路线图）。**不要回答"可以考虑xxx"——直接引用这两个文件。**

qing-learning 采用**双轨制**架构（市场认知层 vs 操作工具层），这对下游 skill 有明确影响：

| 下游 Skill | 影响 | 处理方式 |
|-----------|------|---------|
| `qing-stock-analysis` | 检索 claims 时需区分市场认知 vs 技术工具 | 技术 claims 只作为工具引用，不用于判断当前市场方向 |
| `qing-methodology-review` | 技术 claims 不参与 drift/contradiction 分析 | 跳过 `claim_type: technical-knowledge` 且 `timeframe: permanent` 的 claims |
| `stock-research-engine` | 无直接影响 | 通用个股研究工具，不依赖 qing-learning claims |
| `valuation-analysis` | 无直接影响 | 基于《股市真规则》方法论，独立于博主内容体系 |

详见 `references/dual-track-compatibility.md`。

> **⚠️ 关于"推理模式是否只能针对单一方向"：** 当用户质疑 `framework/reasoning-patterns.yaml` 中的推理思路"只能从单个文件提取、不够通用"时，答案已在 `references/reasoning-pattern-cross-direction-reuse.md`（通用框架的 `examples` 天然支持跨方向复用——同一推理骨架适用于 MLCC/PCB/存储/硅片等不同主题）和 `references/reasoning-pattern-extraction-workflow.md` §8（Phase 6 设计演进：从 116 个独立模式到 10 个通用框架+examples 的演进逻辑）。**不要回答"可以考虑xxx"——直接引用这两个文件。**

## 触发

**Ingestion 触发**（学习新内容）：

- `ing`
- 学习今天内容
- 消化这篇早盘/午盘/复盘
- 更新博主方法论
- 处理 Raw 中的新稿
- 使用 qing learning skills 学习新增文档
- 整理用户直接提供的原始文档（按 raw 格式规范化，**不要假设来源是语音转录**，直接处理原文即可）
- 修正 raw 文档中的错别字/口误（如录音转文字残留错误）
- 用户直接提供博主评论/动态内容，要求补充到文档并学习（手动录入流程）

**Review 触发**（复盘检查）：

- `qing review`
- 方法论复盘
- `review claims`
- 检查一致性
- 检查某段时间的 claims 一致性
- 发现矛盾或观点变化，要求分析
- 周期性方法论 review（默认最近7天，可指定日期范围/主题/claim ID）

## 用户偏好

- **文档驱动执行**：当用户提供文档（README、spec、JSON）描述任务时，直接读取并执行，无需逐步确认。
- **简洁交互**：用户偏好简短回复，不喜欢过度解释。多步骤任务（如 ingestion、持仓更新、观察池更新）执行完毕后，**主动简要汇报结果**（如"Done. 已学习 3 篇 raw，生成 12 条 claims，更新 wiki/总纲"），不要等用户问"处理完了吗"。汇报格式：一句话总结 + 关键数字 + 下一步可选动作。
- **用户纠正时的响应**：当用户指出错误（如"昨天不是说MLCC是韭菜行为吗？今天还可以买？"），立即修正，不辩解。修正后简要确认，不展开解释原因。**此类纠正属于 claims 一致性校验失败的典型信号——策略配置与博主最新纪律矛盾。修正后应检查：①对应 claim 是否已正确标注 ②strategy_pack 中是否还有同类矛盾 ③是否需要更新 claims-consistency-check 参考文档**。这是 claims 一致性校验失败的典型信号——策略配置与博主最新纪律矛盾。
- **内容验证优先**：检查文件是否已处理/已存在时，不能只比较文件名或标题，必须读取原文内容提取唯一标识（如 `dynamic_id`、独特短语）进行交叉验证。
- **优先处理文档，后改脚本**：当用户同时要求"补充到文档"和"改脚本"时，**先完成文档录入和 qing-learning 流程，再处理脚本修改**。用户明确偏好"先不改脚本，先处理文档"。这是硬性优先级，不要试图并行处理或先改脚本后补文档。
- **分阶段实施需用户确认**：当方案涉及多个阶段（如"先做A，再做B"），先向用户说明阶段划分并确认顺序，再执行。用户明确纠正过"先做embedding+LLM rerank的两阶段方案，再做extract脚本改造"——此类跨阶段任务必须获得用户确认。
  - **不要假设默认顺序**：即使技术上有依赖关系（如A是B的前提），也要先列出阶段并让用户确认执行顺序
  - **确认方式**：明确说"方案分N个阶段：①... ②... ③... 您希望按这个顺序执行吗？还是需要调整？"
  - **用户说"先做X"时**：立即停止当前计划，按用户指定的顺序重新规划，不要争辩技术依赖关系
- **Git 拉取优先于本地修改**：当用户要求"拉取远程分支"或"同步最新改动"时，必须先处理 git 同步（fetch/merge/pull），再处理本地数据更新。如果本地有未提交修改：
  1. `git stash` 暂存本地改动
  2. `git fetch origin` + `git merge origin/master` 合并远程
  3. 检查合并结果（`git diff --cached --stat`）
  4. `git merge --abort` 清理预览状态
  5. `git stash pop` 恢复本地改动
  6. 解决冲突（优先接受远程版本，再重新应用本地数据）
  7. 提交并推送
- **远程版本优先原则**：对于 `watchlist.yaml`、`strategy_pack.yaml` 等频繁更新的配置文件，远程版本通常包含更新的市场数据，优先接受远程版本，然后将本地数据（如持仓、今日快照）重新写入
- **直接修复，少解释**：当脚本有bug或遗漏明显内容时，用户偏好直接修复而非长篇解释原因。给出简洁的修复确认即可。
- **脚本清理前先确认历史**：清理旧脚本前，先用 `git log --all --diff-filter=A -- scripts/` 确认哪些脚本是项目原始版本、哪些是手动复制的旧版本。只有确认是历史无用版本才能移入 `deprecated/`。
- **核对未处理文档时，脚本输出不可全信**：`find_unprocessed.py` 按文件名匹配，可能误报（如 claim 中 `source_path` 包含完整路径或不同命名格式）。用户说"核对哪些没处理"时，应直接用 Python 读取所有 claim 的 `source_path` 字段（含正则容错解析失败的YAML），与 raw 文件名做 basename 匹配，给出准确统计。
- **持仓更新完整pipeline**：当用户要求"更新持仓"时，执行完整pipeline：①读取当前positions.yaml和watchlist.yaml → ②获取实时行情计算PnL → ③交叉引用claims判断持仓逻辑是否变化 → ④更新positions.yaml（含closed_positions记录）→ ⑤更新watchlist.yaml today_snapshot → ⑥输出持仓总结+操作建议。不要只改一个文件。
- **操作建议必须关联claims**：给出操作建议时，必须引用具体的claim ID（如claim-20260531-002-a）和博主判断依据，不是拍脑袋建议。
- **持仓更新 factual accuracy 检查**：更新positions.yaml时，必须逐账户核对用户提供的持仓信息。常见错误：把账户2的持仓误写到账户1。写入前反问确认："账户1：XXX，账户2：YYY，对吗？"
- **脚本同步纪律**：当用户要求"同步两边""保持一致"时，指 `~/.hermes/scripts/`（cron 运行时）和 `~/learning-investment-strategies/scripts/`（项目源码）必须双向同步。修改项目版本后，用 `cp` 或软链接确保 cron 版本一致。用户明确说："每次改动都需要保证两边一致"。
- **回顾整理类请求**：当用户要求"回顾整理UP最近观点""qing review"等时，不是走完整 qing-learning 流程（不需要新建 raw/claims），而是基于已学习的 claims 和 wiki 做系统性归纳。输出结构：①周期定位 ②操作策略 ③主线判断 ④新分支/产业催化 ⑤技术分析框架 ⑥风险提示 ⑦观点连续性链条。优先读取 claims 文件（`knowledge/claims/claim-YYYYMMDD-*.yaml`）和 wiki 复盘（`knowledge/wiki/每日复盘/YYYY-MM-DD.md`）作为信息源，不要重新从 raw 抽取。
- **用户发图片整理raw文档时的处理**：当用户发送多张图片（如复盘截图）要求整理成raw文档时，使用OCR提取文字后按raw格式规范化。关键要点：①图片可能包含完整复盘内容，需合并多张图片的OCR结果；②OCR识别可能有误差，需人工校对关键标的名称和数字；③按raw文档标准格式输出（frontmatter、结构化分节）；④保存到`sources/raw/财经/`后走完整qing-learning流程。详见`references/image-to-raw-workflow.md`。
- **短 raw 文档 ingestion 模式**：对于极短 raw（如盘中动态补发，仅1-2句话），不必强行拆成多条 claims。精简为 1-2 条核心 claim，更新对应日期的 wiki（追加章节而非新建页面），不更新 framework/总纲。示例：`早盘补发：26-06-01：周五剧本延续，反向上涨票补跌.md` → 1条 claim（market-cycle）+ wiki 追加盘中补发章节。
- **用户追问"XX方向没有整理吗？"的处理**：当用户发现某主题（如端侧AI、AIPC）只有 claims 而无独立 wiki 专题页时，说明该主题跨多篇 raw 出现但未沉淀为专题。应立即：①搜索所有 raw/claims 中该主题的内容 → ②创建/更新 `knowledge/wiki/市场分析/主题名.md` → ③将相关 claims 链接到专题页 → ④更新 wiki/index.md。这是用户的常见检查模式，应在初始 ingestion 时就主动完成。
- **图片/截图转 raw 的 OCR 处理**：当用户提供复盘截图或图片要求整理时，使用OCR提取文字。注意：①多张图片需合并OCR结果；②关键标的名称和数字需人工校对；③按raw标准格式输出；④详见`references/image-to-raw-workflow.md`。
- **OCR 识别后主动检查图片重叠**：当用户提供多张图片（如早盘截图分两张发送）时，OCR提取后必须主动检查内容是否重叠。方法：比较两张图片的OCR结果，若出现相同章节标题（如"四、板块策略"）或相同段落，判定为重叠内容，去重合并后再写入raw。避免重复内容导致claims抽取冗余。重叠检测实操：对每张图片OCR后先分别保存，用diff或字符串比较检查相邻图片首尾200字，重复率>80%即判定重叠，保留更完整版本。
- **用户发送图片时的日期推断**：当用户提供截图且无明确日期标注时，通过上下文推断日期：①检查图片内容中的时间线索（如"顶部结构第N天"、"调整第N天"）；②与已有raw对比（如昨天是"第15天"则今天是"第16天"）；③确认系统当前日期作为fallback。推断出的日期必须在raw frontmatter中标注，并在正文中说明推断依据。

## 必读参考

### Ingestion 参考
1. 先读 `framework/learning-update-protocol.md`。
2. 抽取 claim 前读 `skills/qing-learning/references/claim-schema.md`。
2b. **编写 claim 前必须读 `references/claim-writing-spec.md`**（面向 Neo4j/Qdrant/Agent 的系统化约定：字段职责矩阵、多方向 raw 的「总入口」结构、subject/statement 编写规范、常见反模式、验证清单）。
3. 遇到矛盾观点时读 `framework/contradiction-policy.md`。
4. **B站UP主动态抓取**：参考 `references/bilibili-up-fetch.md`（充电专属动态图片处理、Playwright截图、与qing-learning pipeline集成）。
5. **B站API调试**：参考 `references/bilibili-api-debugging.md`（错误码速查、UID验证、cookie模板、常见误区）。
6. **OCR 图片转文字**：参考 `references/ocr-workflow-v2.md`（RapidOCR 首选、Tesseract fallback、常见错误修正）。
7. **数据源切换**：参考 `references/data-source-fallback.md`（东方财富被拒绝时切换到新浪财经的API用法和验证方法）。
8. **Pipeline QA 与去重**：参考 `references/pipeline-qa-dedup.md`（original→raw 遗漏检查、重复抓取根因分析）。
9. **知识库同步**：参考【知识库增量同步】章节（claims/wiki 落库后必须同步到 Neo4j + Qdrant，否则 Qing-Agent 无法检索到新内容）。
5. `references/bilibili-up-comment-terminology.md`（区分真正的UP置顶评论 vs 截图第一条评论，避免 claims 引用标注错误）。
6. **YAML 特殊字符转义**：参考【已知问题与解决】→"YAML 特殊字符转义"（claim 文件编写时避免中文引号、冒号导致解析失败）。
7. **Claim Schema 验证**：参考 `references/claim-schema-validation.md`（必需字段、枚举值、验证命令、常见错误速查）。
7. **学习索引交叉验证**：参考 `references/learn-index-cross-validation.md`（双重验证确保100%学习覆盖率）。
8. **学习索引**：参考【学习索引 (Learn Index)】章节，追踪所有 raw 文档的学习状态。
9. **观察池 themes 恢复**：参考 `references/watchlist-theme-recovery-from-git.md`（从 git 历史恢复被误删的 watchlist themes，含一键恢复脚本）。
10. **观察池 themes 合并去重**：参考 `references/watchlist-theme-merge-dedup.md`（恢复历史 themes 后合并重复标的、保留旧 themes 的去重流程）。
12. **双轨制兼容性**：参考 `references/dual-track-compatibility.md`（双轨制对其他 skill 的影响和兼容要求）。
13. **用户直接提供 UP 评论时的处理**：参考【用户直接提供 UP 评论时的处理流程】（检查是否已自动抓取、区分文档录入与数据查询、claim 抽取要点）。
14. **Patch/编辑前必须完整读取文件**：如果文件之前是用 `offset`/`limit` 读取的，在 patch 前必须重新完整读取（不带分页参数），否则匹配失败。详见【已知问题与解决】→"Patch/编辑前必须完整读取文件"。
15. **Skill 同步工作流**：参考 `references/skill-sync-workflow.md`（项目 skill 与 Hermes 全局 skill 的合并、配置更新、验证流程）。
16. **Trading Rules 迁移与维护**：参考 `references/trading-rules-migration-guide.md`（何时将操作纪律进 `framework/trading-rules.md`、迁移流程、避免重复）。
18. **专家思维蒸馏**：参考 `references/expert-distillation-guide.md`（Prompt+RAG/Fine-tune/Agent三条技术路径）。
19. **推理模式架构**：参考 `references/reasoning-pattern-architecture.md`（三层蒸馏架构：知识库层→推理模式层→动态应用层，含YAML模板和实施路线图）。
19. **推理模式抽取脚本**：参考 `references/reasoning-pattern-extraction-workflow.md`（批量从 raw 抽取推理模式写入 `framework/reasoning-patterns.yaml`，含脚本用法、匹配机制、Agent 集成架构）。
20. **推理模式匹配算法优化**：参考 `references/reasoning-pattern-matching-phase5.md`（聚合到10个通用框架后的匹配算法优化：多字段加权索引、精确匹配优先、阈值调整、ONNX Embedding 评估）。
    - **推理模式匹配算法 Phase 6**：参考 `references/reasoning-pattern-matching-phase5.md`（两阶段匹配：ONNX Embedding 召回 Top5 + LLM 重排序 Top3，解决 MLCC/半导体业绩等边界查询的框架归属问题）。
    20. **Phase 6 实施配方**：参考 `references/reasoning-pattern-phase6-recipe.md`（快速复现/验证两阶段匹配 + 框架归类合并的配方、命令、常见边界问题）。
    19. **Phase 6 设计演进 rationale**：当用户质疑"单文件提取是否太窄/不够通用"时，参考 `references/reasoning-pattern-extraction-workflow.md` §8（设计演进：从 116 个独立模式到 10 个通用框架+examples 的演进逻辑、类比、适用边界）。
    22. **Embedding-Friendly Description 编写**：参考 `references/embedding-friendly-description-pattern.md`（当使用 Embedding 语义匹配时，如何编写框架 description 以提升准确率：四段式结构、触发场景、典型查询示例、效果对比）。
    23. **Trading Rules 迁移与维护**：参考 `references/trading-rules-migration-guide.md`（何时将操作纪律进 `framework/trading-rules.md`、迁移流程、避免重复）。
    24. **推理模式跨方向复用性**：参考 `references/reasoning-pattern-cross-direction-reuse.md`（通用框架的 `examples` 列表如何支撑跨方向复用——同一推理骨架适用于不同主题的具体案例、复用边界、何时需要新增框架）。
    25. **推理模式通用性 FAQ**：当用户问"推理模式是否只能针对单一方向""是否不够通用""是不是只能从单个文件提取"时，直接引用 `references/reasoning-pattern-cross-direction-reuse.md` 的"核心结论"和"复用示例"表格。不要重新解释 Phase 6 架构——用户的问题说明已有文档未被有效引用，Agent 应直接展示复用示例（如 `upstream_cycle` 同时支撑 MLCC/PCB/存储/硅片），而非重复论证设计合理性。
26. **非科技方向 Neo4j 图谱设计**：当需要将研报中推荐的个股入库 Neo4j 以便 Qing-Agent 检索时，参考 `references/non-tech-stock-graph-design.md`（四种节点：Theme/Stock/Claim/ResearchReport + 五种关系 + Agent 检索路径）。
27. **混合内容 ingestion（轨道A+轨道B 同 raw）**：参考 `references/mixed-content-ingestion.md`（单篇 raw 同时含技术教学和行情观点时的拆分规则、文件编号惯例、反面案例）。
28. **Qdrant 向量损坏排查**：参考 `references/qdrant-corruption-root-cause.md`（根因链、为什么只 claims 不 documents、`--force-recreate` 一键修复、完整性自检机制）。
29. **Claim intensity 分级**：参考 `references/claim-writing-spec.md` §「Agent 消费规则（intensity 分级）」和 `references/claim-schema-validation.md` §「Intensity 自动回填」。
30. **Claim intensity 回填脚本**：`scripts/backfill_claim_intensity.py` — 对已有 claims 自动分类 intensity（8条规则），生成 `logs/intensity_backfill_report.txt` 审计报告。
31. **Neo4j 关系更新流水线**：参考 [`docs/neo4j-relation-pipeline.md`](../../docs/neo4j-relation-pipeline.md)（完整四步流程：discover → Neo4j migrate → Qdrant rebuild → restart Agent，每步命令、原理、常见陷阱、定时维护建议）。
32. **发现进度汇报脚本**：`scripts/run_discover_with_progress.sh`（skill 内脚本副本，与原项目 `scripts/` 下同步）。
33. **外部研究报告处理**：参考 `references/external-research-handling.md`（投行报告不入 qing-learning，独立归档到 `sources/research/`，按 UP 延迟规则标注时效）。
33. **外部研究报告归档**：参考 `references/external-research-archiving.md`（投行报告不进入 qing-learning 流程，存入 `sources/research/`，按 UP 指定的延迟窗口到期再评估）。

32. **外部研究报告处理**：参考【外部研究报告处理规则】和 `references/external-research-handling.md`（投行/券商报告不入 raw/不提取 claims，单独归档到 `sources/research/`，标注 UP 的延迟判断和回看时间）。

### Review 参考
1. `framework/methodology-review-protocol.md`
2. `framework/contradiction-policy.md`
3. `references/methodology-review-protocol.md`
4. `references/review-report-template.md`
5. `references/review-execution-script.py` — 辅助分析脚本

## Ingestion 工作流程

1. 运行 `scripts/find_unprocessed.py` 找未处理 raw（如果存在）。
2. 每次默认只处理一篇 raw，除非用户明确要求批量。
3. LLM 必须阅读全文后再写入任何结论。
3b. **⚠️ 整理完成后必须对照原文核验完整性**：raw 文档结构化整理完成后，**必须逐段回原文检查**，确认：
    - 每个话题段在 raw 中有对应（尤其注意**文档首尾段**——长文档处理时尾部最容易漏）
    - 口语中的**力度词**（炸裂/特别/非常/很牛）是否被弱化为平淡书面语
    - UP 随口举例的**标的名称**是否被收录（即使只是举例，也要保留）
    - UP 推荐的**旧内容交叉引用**（如「去看 X 月 X 号视频」）是否保留
    - **不确定的文字或内容，必须向用户提问确认**——不要猜、不要跳过、不要自行改写
4. **检查文档是否已存在**：处理前确认该 raw 是否已在 `sources/raw/财经/` 中，以及是否已有对应 claims/wiki。详见【已知问题与解决】→"重复处理已存在的文档"。
5. **用户直接提供内容时的手动录入**：若用户直接转述/粘贴博主评论或动态内容（非来自 fetch 脚本），先保存为 raw 文件，再走完整 qing-learning 流程。详见【手动录入流程】。
6. **读取 claim schema**：抽取 claims 前，先读 `references/claim-schema.md` 确认字段和枚举要求。避免 YAML 格式错误导致后续流程中断。
7. 先抽取 claims，再更新 wiki、methodology、framework。
8. **更新关联 wiki 专题页**：抽取 claims 后，检查 claim 涉及的主题是否已有独立 wiki 专题页（如`端侧AI`、`AIPC`、`超级电容`等）。若已有专题页，将新 claim 关联到该页面；若无专题页但该主题已跨多篇 raw 出现，考虑创建专题页。不要只更新每日复盘 wiki 而遗漏专题沉淀。
9. 只有满足 durable rule 的观点才进入 framework。
   - **Framework 更新后检查 prompt 同步**：若更新的 framework 文件涉及大盘分析的输出格式规范（如 11 项分析框架、周期判断标准、板块映射模板等），必须检查并同步更新 `prompts/system/market_analysis_framework.txt`。该文件是 agent 输出格式的单一来源（source of truth），与 `framework/` 知识沉淀层分离——前者控制 AI 输出结构，后者控制投资方法论内容。两者更新不同步会导致 agent 输出格式与最新方法论脱节。
10. **更新三个索引文件（缺一不可）**：
    - `knowledge/claims/index.md` — claim 文件索引
    - `knowledge/wiki/index.md` — wiki 页面索引（常被遗漏！）
    - `knowledge/wiki/log.md` — 操作日志
11. 判断是否需要更新 `knowledge/wiki/投资方法论/博主方法论总纲.md`。
12. **推理模式抽取**：从 raw 中识别 ≥3 步可复用的推理链（非观点，是"怎么推理"），
    使用 `scripts/extract_reasoning_patterns.py` 抽取并写入 `framework/reasoning-patterns.yaml`。
    详见 `references/reasoning-pattern-extraction-workflow.md`。

    **触发条件**：raw 文件含 `复盘`/`视频`/`产业链`/`拆解`/`BOM` 等关键词，正文前 500 字含 `因为`/`所以`/`判断`/`逻辑` 等分析性语言。

    **不要**在每篇 raw ingestion 时都运行——只在 raw 内容明显包含分析框架时才触发。
    日常动态/简讯类 raw 通常不含推理链，跳过即可。

    **Phase 6 改造要点**：单文件提取后，脚本不再直接新增独立 pattern，而是让 LLM 判断归入10个通用框架中的哪一个，作为该框架的 `examples` 追加。这解决了之前116个单raw模式（99.1%只关联1个raw）的问题。详见 `references/reasoning-pattern-extraction-workflow.md` §8。
13. 输出 Learning Update Report。
13. **知识库增量同步**：运行三个增量同步脚本，将新的 claims 和 wiki 推送到 Qing-Agent 的检索后端。

    **⚠️ 前置步骤：Qdrant 本地模式独占文件锁**
    Qing-Agent 启动后会持有 `.qdrant_data/` 的独占锁。索引脚本无法与 Agent 同时运行（会报 `Storage folder already accessed` 或静默卡死）。**索引前必须先关 Agent。**

    > 💡 **脚本已内置自动杀 Agent**（2026-06-07）：`index_claims_to_qdrant.py` 和 `index_documents_to_qdrant.py` 启动时自动 SIGTERM→SIGKILL uvicorn 进程，然后等待 `.qdrant_data/.lock` 释放。以下手动关 Agent 步骤为兜底方案。

    **⚠️ 三个脚本必须串行运行，不能并行！** 并行运行会导致两个 QdrantClient 同时访问同一 SQLite → 向量存储损坏。

    ```bash
    # 1. 关 Agent（脚本自动杀失败时的兜底）
    kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null

    # 2. 增量同步 — 串行！一个接一个跑
    cd ~/learning-investment-strategies
    PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_documents_to_qdrant.py   # 文档 → Qdrant
    .venv/bin/python scripts/migrate_claims_to_neo4j.py                        # claims → Neo4j
    .venv/bin/python scripts/index_claims_to_qdrant_monitored.py               # claims → Qdrant（带监控+自检）

    # 3. 重启 Agent
    nohup .venv/bin/uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
    ```

    - 增量模式（默认）：只处理 `hash 有变化` 或 `新创建` 的文件，增量 < 30 秒
    - 强制全量模式（数据损坏时）：`--force-recreate`（claims Qdrant，删旧collection→全量重建+自检）或 `--force-full`（文档 Qdrant）
    - **必须在 git commit 之后运行**（脚本基于文件 hash 判断是否已同步）
    - **⚠️ 同步后必须验证 Agent 能否检索到新内容**（见 Pitfall #15）
    - **常见陷阱**：`PYTHONUNBUFFERED=1` 是关键——否则 Python stdout 缓冲导致进程管理捕获不到输出。ONNX 单线程（`intra_op_num_threads=1`）在 2 核 VM 上必须设置，否则 futex spin-lock 死锁。
    - **索引脚本已内置 Agent 杀进程 + 锁等待**（2026-06-07）：不再需要手动 `kill` Agent，脚本启动时自动处理。手动 kill 仅作备用。

### Ingestion 关键 Pitfalls

1. **遗漏 wiki/index.md 更新**：`knowledge/wiki/index.md` 是最容易被遗漏的索引文件。每次更新 wiki 页面（尤其是新增专题页或每日复盘）后，必须检查并更新 wiki/index.md。若新增专题页未加入索引，用户后续无法通过索引发现该页面。
2. **跳过 claim schema 直接写 claims**：不写 claims 前不读 `references/claim-schema.md` 是常见错误。虽然 LLM 生成的 YAML 通常格式正确，但字段缺失、枚举值错误、特殊字符未转义等问题只有在对比 schema 后才能避免。一次 YAML 格式错误会导致后续自动化流程（索引生成、wiki 链接、矛盾检测）全部中断。
3. **重复处理已存在的文档**：处理前未检查 `sources/raw/财经/`、`knowledge/claims/`、`knowledge/wiki/每日复盘/` 中是否已有对应内容，导致重复创建 claims 或 wiki 冲突。
4. **用户说"核对/确认哪些没处理"时，脚本匹配不可靠**：`find_unprocessed.py` 按文件名匹配，但 claim 中的 `source_path` 可能包含完整路径或不同命名格式。正确核对方式：读取所有 claim 文件的 `source_path` 字段（用正则容错解析YAML失败的文件），与 raw 文件名做 basename 匹配，给出准确统计。
5. **随意关联 related_stocks 而不验证业务对齐**：撰写 claims 时，仅凭板块/主题分类（如「都是数据库」）就把标的加入 `related_stocks`，未验证其具体产品/技术是否真正对齐 claim 的核心逻辑。反面案例：NVIDIA GPU-Native 数据库催化，星环科技有 Transwarp GPU-Native 产品，但海量数据主营 Vastbase（openGauss 关系型数据库），两者产品完全不同——仅因「都是国产数据库」就关联属于错误。规则：添加到 `related_stocks` 前，必须确认该标的真的有对应产品/技术，不能仅凭板块分类。
6. **遗漏标记 raw 和 original 文件为 processed**：完成 claims/wiki/framework 更新后，必须同步更新：
   - `sources/original/bilibili/*.md` 中的 `unprocessed: true` → `unprocessed: false`（仅对已学习的内容做此标记）
   - `sources/raw/财经/*.md` 中的 `ingest_status: pending` → `ingest_status: processed`
   - 否则下次 Pipeline QA 会重复检查这些文件。这是 ingestion 流程的最后一步，和更新索引同等重要。
7. **遗忘知识库同步**：claims/wiki 落库并提交后，若不运行 `index_documents_to_qdrant.py` + `migrate_claims_to_neo4j.py`，Qing-Agent 将无法检索到新内容。特征：用户询问某个新学的板块时，Qing-Agent 回答"未找到相关数据"。检查 `.index_state.json` 和 `.migrate_state.json` 的 `last_sync` 时间戳可快速确认是否遗漏。
8. **未关 Agent 就运行同步脚本（Qdrant 本地模式）**：Qing-Agent 启动后持有 `.qdrant_data/` 独占文件锁。不关 Agent 直接运行索引脚本会导致 `Storage folder already accessed` 错误或静默卡死。正确流程：`kill` Agent → 同步 → 重启 Agent。详见步骤13「知识库增量同步」。
9. **忘记 PYTHONUNBUFFERED=1**：Hermes cron/后台进程管理器捕获 Python stdout 时，默认缓冲会导致无输出（看起来像卡死）。索引命令必须加 `PYTHONUNBUFFERED=1` 前缀。详见步骤13。

10. **Qdrant claims 索引报向量维度错误（已修复 2026-06-07）**：

    **错误症状**：`ValueError: could not broadcast input array from shape (512,) into shape (1,)`
    **根因**：Qdrant 本地模式（`QdrantClient(path=...)`）底层 SQLite 不支持并发访问。当 Agent 未关闭时运行索引脚本，或两个索引脚本并行运行 → 并发写入竞争 → SQLite 向量存储内部某条记录维度错乱（shape `(1,)` 而非 `(512,)`）。之后每次增量 upsert 到该坏记录触发崩溃。

    **一键修复**（2026-06-07 新增）：
    ```bash
    .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate
    ```
    此命令自动执行：杀 Agent → 等锁释放 → 删旧 collection → 重建 → 全量索引 → 完整性自检（随机抽样10条验证维度=512）。

    **防护机制**（2026-06-07 已集成）：
    - 两个索引脚本（`index_claims_to_qdrant.py` / `index_documents_to_qdrant.py`）启动时**自动 kill uvicorn Qing-Agent**（`--skip-agent-kill` 可跳过）
    - 等待 `.qdrant_data/.lock` 释放（最多 30s）
    - `index_claims_to_qdrant.py` 索引后**完整性自检**（随机抽样10条验证向量维度=512，异常时退出码=2）
    - 若需手动控制：`--skip-agent-kill` 跳过 Agent 杀进程（危险）

11. **Claim 文件编号与已有 claims 冲突**：同一日期可能已有其他 session 或同一 session 的不同子 agent 创建了 claims。**写入前必须检查**：
    ```bash
    ls knowledge/claims/claim-YYYYMMDD-*.yaml 2>/dev/null | tail -5
    ```
    若 `claim-20260604-001.yaml` 已被占用 → 按序递增命名（如 `claim-20260604-004.yaml`）。**不要**用 `write_file` 覆盖已有文件——会丢失之前 session 提取的 claims。若已意外覆盖，立即 `git checkout HEAD -- <file>` 恢复。同时，`mv` 重命名后必须 `sed -i` 批量替换文件内的 claim ID 引用。
21. **`discover_claim_relations.py` 常见陷阱**：此脚本用于自动发现 claim 间的 SUPERSEDES/CONTRADICTS/SUPPLEMENTS 关系。
    - **没有 `--all` 模式**：脚本只支持 `--file`、`--claim-id`、`--all-missing`。不要编造不存在的 CLI 参数——先读 `--help` 或脚本源码确认。**真实后果（2026-06-07）**：Agent 错误认为存在 `--all` 模式，将原本单一的 `--all-missing` 任务拆分为"已结束的 `--all`"和"当前运行的 `--all-missing`"两个任务，用户明确纠正了这一误解。中断后重新运行 `--all-missing` 就是续跑，不需额外管理。
    - **YAML 缩进 corruption**：`write_results_to_yaml()` 曾硬编码 4 空格前缀写入 `supersedes:`/`contradicts:` 字段，导致 YAML 解析失败（42 个文件被损坏，错误模式：`mapping values are not allowed here` 或 `expected <block end>, but found '<block mapping start>'`）。**已修复**：改为保留原始缩进（`line[:len(line) - len(line.lstrip())]`）。若重跑旧版本脚本，会导致新一轮 corruption。
    - **修复已损坏文件**：`git checkout -- knowledge/claims/` 恢复干净版最快。不要逐文件手工修——42 个文件有 162 行缩进错误。
    - **项目使用 `.venv` 不是 `venv`**：两个 venv 都存在于项目目录下，只有 `.venv/bin/python` 包含 `langchain_openai` 等完整依赖。
    - **进度汇报 wrapper**：长任务（500+ claims × 10s/条 ≈ 90分钟）建议用 `scripts/run_discover_with_progress.sh`，每 10 分钟输出进度到日志文件 + `progress_reporter` 后台进程。中断时自动记录 exit code 原因（SIGTERM/SIGKILL/OOM/正常完成）。使用方式：`terminal(background=True, notify_on_complete=True)` 运行 wrapper。
    - **续跑机制**：`--all-missing` 只处理尚无 `supersedes`/`contradicts` 的 claims，天然支持中断续跑——已处理过的自动跳过。
    - **完整流水线**：关系发现是第一步，完成后必须运行 `migrate_claims_to_neo4j.py` → `index_claims_to_qdrant.py --force-recreate` → 重启 Agent。详见 `docs/neo4j-relation-pipeline.md`。

11. **推理模式抽取混淆观点与推理**：`"UP看好MLCC"` 是观点，应进 claims；`"UP是怎么得出看好MLCC的（5步推理链）"` 是推理模式，应进 `framework/reasoning-patterns.yaml`。不要将单日盘面判断误标为推理模式。
12. **单raw依赖陷阱——批量抽取后必须聚合**：`scripts/extract_reasoning_patterns.py` 批量抽取时，会把每篇含推理链的 raw 都生成一个独立模式。运行一段时间后会出现：①99%的模式只关联1个raw ②主题高度重叠 ③文件持续膨胀无收敛 ④匹配噪声增大。**解决方案**：
    - **长期方案（推荐）**：抽取时直接让 LLM 判断归入10个通用框架，作为 `examples` 追加。这是 Phase 6 改造后的默认行为，详见 `references/reasoning-pattern-extraction-workflow.md` §8。
    - **历史补救**：若已积累大量独立模式，定期（如每新增50个模式后）执行聚合——按推理结构相似性将模式聚类为通用框架（如`upstream_cycle`、`mainline_identification`等），每个框架保留通用`reasoning_chain`+原模式作为`examples`。聚合后模式数从116→10，文件大小从255KB→78KB，主题覆盖率保持100%。详见 `references/reasoning-pattern-extraction-workflow.md` §7。
13. **用户质疑推理模式通用性时的响应方式**：当用户问"推理思路都是从单个文件提取的是否不够通用""只能针对一个方向吗"时，**不要重新解释 Phase 6 设计 rationale**——直接展示 `references/reasoning-pattern-cross-direction-reuse.md` 中的复用示例表格（`upstream_cycle` 支撑 MLCC/PCB/存储/硅片等），用具体案例回答。用户的问题通常意味着已有文档未被有效发现，Agent 应充当文档导航器而非重新论证者。

14. **Claim 编写规范（系统性约定）**：写 claim 时必须遵循 `references/claim-writing-spec.md`。核心原则：①`subject` 和 `statement` 是唯一影响 Qdrant 搜索召回率的字段（`interpretation`/`evidence_quote` 不参与嵌入）；②方向推荐类 claim 的 `statement` 必须自包含标的代码（Neo4j 用正则从 subject+statement 提取 6 位代码建 Claim→Stock 边，Agent 不遍历图找标的）；③多方向 raw 需设「总入口」claim（claim-a 汇总全部方向+标的）；④`claim_type` 影响 Neo4j 实体标签和 Agent 方法论过滤器的行为。详见 `references/claim-writing-spec.md`。
14. **Claim 文件编号冲突（同一日期多次 ingestion）**：同一日期可能有多篇 raw 需要学习（早盘、盘中动态、盘后视频等），每次 ingestion 生成独立的 claim 文件（`claim-YYYYMMDD-001.yaml`、`-002.yaml`...）。**新建前必须检查已有编号**：
    - `ls knowledge/claims/claim-YYYYMMDD-*.yaml` 确认已有编号
    - 直接写入目标编号文件，不要先写成 `-001` 再 `mv` 重命名——`write_file` 会覆盖已有文件，导致旧 claims 丢失
    - 若已误覆盖：立即 `git checkout HEAD -- <旧文件>` 恢复，再写入正确编号的新文件

15. **Qdrant Claims 索引失败 + Agent 检索不到新内容**：症状：Neo4j 同步成功、文档 Qdrant 索引成功，但 Agent 的 `/chat` 仍返回旧数据。**排查步骤**：
    - 若 `index_claims_to_qdrant.py` 非零退出 → 常见为向量损坏（见 Pitfall #10），用 `--force-recreate` 修复
    - 索引成功后 Agent 仍检索不到 → 检查 `.qdrant_data/collection/qing_claims/storage.sqlite` 是否被另一进程锁定
    - **验证方法**：索引用 `index_claims_to_qdrant_monitored.py`（带监控日志），确认退出码=0 且日志显示 `✅ Indexed N claims`
    - **修复**：`--force-recreate` 一键修复（自动杀Agent→重建collection→全量索引→完整性自检）

16. **Agent 不显示 claim 内容时，按三层排查（claim → prompt 构建 → Agent 代码）**：当 Agent 回答缺少某条 claim 的关键信息时，按以下顺序排查——
    ① **claim 层**：statement 是否超 200 字被截断？subject 是否包含搜索关键词？claim_type 是否正确（methodology/operation 进入可引用区块，其他进入时效分级）？
    ② **prompt 构建层**：Qdrant payload 是否包含 `claim_type` 字段（否则分流失效）？context 构建是否区分了方法论/最新/近期/历史四个区块？
    ③ **Agent 代码层**：`_filter_methodology_only` 是否误筛了 ≤7天 market-cycle claim？核心原则是否一刀切「仅供参考」？
    **只有①②③都排查后才考虑改 Agent 代码**。反面案例（2026-06-07）：
    - 误改截断 200→300 → 实际是 claim-a 从 242 压缩到 207 字（①）
    - prompt 不区分方法论/观点区块 → 改为二分区块 + 时效分级（②）
    - 漏了 `claim_type` 字段 → 补上后分流生效（③）
    原则：claim 是知识载体→prompt 是消费管道→Agent 是执行层。修复也应从上到下，不要跳过层级直接改 Agent。

17. **raw 文档整理遗漏——三种典型类型**：用户直接提供文档时，整理后可能发生以下遗漏（2026-06-07 真实案例）：
    - **尾部遗漏**：长文档处理时对结尾段关注度下降，尤其最后一个话题段容易被跳过
    - **力度弱化**：LLM 倾向将口语规范化，UP 的力度词被降级——「一季报特别炸的」→「一季报可以的」
    - **案例丢失**：LLM 提取方法论时丢弃了 UP 当场举例的具体标的
    - **防范**：严格按工作流程 3b 逐段核验。不确定时主动向用户提问。

18. **混合内容 ingestion 未分轨**：单篇 raw 同时包含技术教学和行情观点时，把所有 claims 都写入同一个文件。这会导致：①permanent 知识与 time-limited 观点混在一起 ②Agent 检索时无法区分 ③时效管理混乱。**正确做法**：拆分为两个独立 claim 文件——`-001.yaml`（轨道A，行情观点，short/medium-term）+ `-002.yaml`（轨道B，技术知识，permanent）。详见 `references/mixed-content-ingestion.md`。

19. **成对概念文档不对称**：当文档同时覆盖两个成对的形态（如上吊线↔铁锤线、流星线↔倒装铁锤线、高档长黑↔低档长黑），容易只给空方变体详细解释而缩减多方变体为一行。反面案例（2026-06-07）：上吊线有详细的反直觉要点+化解条件+对比表，铁锤线只有一行「看多信号」。用户指出"只介绍了上吊线和流星线，铁锤和倒装铁锤是什么意思？为什么没有在文档里"——这暴露了**写文档时注意力集中在需要行动的空方信号上，忽略了对称的多方信号也应该有同等篇幅的解释**。规则：成对概念的文档必须对称——两个变体都应包含定义、信号本质、交易逻辑、具体操作。不要因为一方需要行动就只写它。

20. **配对形态的定义段只描述共同特征不命名变体**：当两个变体共享同一形态特征但含义相反时，定义段容易只写「实体很小，下影线极长」就跳转到表格。这导致读者不知道这个形状在不同位置叫什么。反面案例（2026-06-07）：§1.3 定义段只写了共同形态，铁锤线和倒装铁锤线只有在表格里才被命名。用户说「这两个线的定义你有补上去吗？好像我没看到它的定义」。规则：定义段必须在共同特征之后**明确列出两个变体的名称和各自含义**，格式为「- **上吊线**：上述形态出现在上涨末端 → ...\\n- **铁锤线**：上述形态出现在下跌末端 → ...」。

21. **同日 wiki 覆盖——写入前必须检查已有内容**：同一日期可能已有其他 session 或子 agent 创建的 wiki（如技术分析课 + 周复盘同一天）。**写每日复盘 wiki 前必须先用 `read_file` 读取已有内容**，确认是否需合并而非覆盖。反面案例（2026-06-07）：用 `write_file` 写入周复盘 wiki 覆盖了已存在的「技术分析课程学习」wiki（丢失了 K 线形态表格和 5 条行情判断）。修复方式：`git show HEAD:path` 恢复原内容 → 合并两部分为一个文件。规则：①同日期多轨道内容应合并到同一 wiki 文件（用 ## 分割轨道A/轨道B）②写入前先读已有文件 → 如有内容则合并 → 更新 index.md 描述。

21. **同日期 wiki 覆盖——双轨内容合并而非覆盖**：当同一日期已有 wiki（如轨道B技术课程学习），现在又要写入新内容（如轨道A周复盘）时，**不能直接用 `write_file` 覆盖**。反面案例（2026-06-07）：`每日复盘/2026-06-07.md` 已存在（技术分析第二课学习），agent 直接覆盖为周复盘内容 → 丢失了轨道B的 K 线形态表格和 claims 引用。**正确做法**：①用 `ls` 或直接 `read_file` 检查目标 wiki 是否已存在（不要只依赖 `search_files`——可能返回空结果）→ ②若已存在，读取原文 → ③合并两个内容到同一文件，用 `## 一、...（轨道B）` + `## 二、...（轨道A）` 分区 → ④更新 wiki/index.md 中该条目的描述以反映合并内容。恢复已覆盖文件：`git show HEAD:path > path`。

22. **`search_files` 不能可靠判定文件不存在**：`search_files` 对含中文路径或特殊字符的目录可能返回空结果，即使文件确实存在。反面案例（2026-06-07）：`search_files(pattern='2026-06-07', path='knowledge/wiki')` 返回 0 结果，但 `每日复盘/2026-06-07.md` 实际存在。**规则**：判定文件是否存在时，用 `ls <path>` 或 `read_file(path)` 做确定性检查，不要依赖 `search_files` 的搜索结果。

## Review（方法论复盘）工作流程 **配对形态的定义段只描述共同特征不命名变体**：当两个变体共享同一形态特征但含义相反时，定义段容易只写「实体很小，下影线极长」就跳转到表格。这导致读者不知道这个形状在不同位置叫什么。反面案例（2026-06-07）：§1.3 定义段只写了共同形态，铁锤线和倒装铁锤线只有在表格里才被命名。用户说「这两个线的定义你有补上去吗？好像我没看到它的定义」。规则：定义段必须在共同特征之后**明确列出两个变体的名称和各自含义**，格式为「- **上吊线**：上述形态出现在上涨末端 → ...\\n- **铁锤线**：上述形态出现在下跌末端 → ...」。

21. **同日期 wiki 覆盖——双轨内容合并而非覆盖**：当同一日期已有 wiki（如轨道B技术课程学习），现在又要写入新内容（如轨道A周复盘）时，**不能直接用 `write_file` 覆盖**。反面案例（2026-06-07）：`每日复盘/2026-06-07.md` 已存在（技术分析第二课学习），agent 直接覆盖为周复盘内容 → 丢失了轨道B的 K 线形态表格和 claims 引用。**正确做法**：①用 `ls` 或直接 `read_file` 检查目标 wiki 是否已存在（不要只依赖 `search_files`——可能返回空结果）→ ②若已存在，读取原文 → ③合并两个内容到同一文件，用 `## 一、...（轨道B）` + `## 二、...（轨道A）` 分区 → ④更新 wiki/index.md 中该条目的描述以反映合并内容。恢复已覆盖文件：`git show HEAD:path > path`。

22. **`search_files` 不能可靠判定文件不存在**：`search_files` 对含中文路径或特殊字符的目录可能返回空结果，即使文件确实存在。反面案例（2026-06-07）：`search_files(pattern='2026-06-07', path='knowledge/wiki')` 返回 0 结果，但 `每日复盘/2026-06-07.md` 实际存在。**规则**：判定文件是否存在时，用 `ls <path>` 或 `read_file(path)` 做确定性检查，不要依赖 `search_files` 的搜索结果。

## Review（方法论复盘）工作流程

当用户触发 review 时，执行以下流程：

### Step 1: 确定 Review 范围

- 默认：最近 7 天（含今天）
- 用户可指定：日期范围、特定主题、特定 claim ID

### Step 2: 读取 Claims

```bash
cd /home/ubuntu/learning-investment-strategies
grep "source_date:" knowledge/claims/claim-YYYYMMDD-*.yaml
```

- 读取窗口内所有 claim 文件
- 注意 YAML 解析错误（部分文件可能有格式问题），跳过错误文件继续
- 提取：date, topic, text, type, confidence, status, supersedes, contradicts

### Step 3: 统计分析

- 每日 claim 数量
- 主题分布（Top 20）
- Claim type 分布（sector-theme, operation, market-cycle, methodology, risk 等）
- Confidence 分布
- Status 分布（active/superseded）
- 有 supersedes/contradicts 的 claims

### Step 4: 主题漂移分析

对跨日期出现多次的主题，按时间线排列，判断变化类型：

| 变化类型 | 含义 | 示例 |
|----------|------|------|
| no-change | 观点一致，重复确认 | 同一策略多天强调 |
| clarification | 细化、补充条件 | 从"做多"到"等缩量才做多" |
| extension | 扩展到新场景 | 从半导体到功率半导体 |
| correction | 修正旧判断 | 波浪结构从ABC修正为A浪 |
| contradiction | 明确矛盾，需标记 | 看多vs看空同一标的 |
| expiration | 观点过期，事件证伪 | 华为韬1不及预期 |

### Step 5: 矛盾识别与分类

按 `framework/contradiction-policy.md` 分类：

| 类型 | 含义 | 处理方式 |
|------|------|----------|
| timeframe-shift | 短期与长期视角不同 | 无需标记，说明时间维度 |
| cycle-shift | 市场阶段变化导致观点变化 | 标记为 cycle-shift，更新 status |
| logic-broken | 个股或板块逻辑被证伪 | 标记 contradicts，旧 claim 更新 status |
| risk-repriced | 宏观/流动性/风险偏好改变 | 标记 risk-repriced |
| true-conflict | 暂无清晰解释，需人工 review | 标记 true-conflict，高亮提醒用户 |

### Step 6: Durable Rule 筛选

只有满足以下任一条件才建议进入 framework：

1. **明确规则**：有具体数字、条件、阈值（如"赚20%砍半仓"）
2. **多次重复**：同一方法论在不同日期出现 2 次以上
3. **解释旧冲突**：能解释之前矛盾的新规则
4. **改变操作纪律**：直接影响买卖/仓位/风控的决策规则

### Step 7: 一致性检查

对新 claims（尤其是当天），检查与前期框架的一致性：

- 是否与现有 durable rule 冲突？
- 是否属于 extension/clarification？
- 是否需要标记 supersedes/contradicts？

### Step 8: 生成报告

输出格式见 `references/review-report-template.md`。

报告保存路径：`reports/methodology-review-YYYYMMDD.md`

### Step 9: Git 提交

```bash
git add reports/methodology-review-YYYYMMDD.md
git status --short
```

### Review 关键 Pitfalls

1. **YAML 解析错误**：部分 claim 文件有格式问题（如特殊字符未转义），跳过错误文件继续分析，不要中断
2. **source_date 位置**：claim 文件根级可能没有 source_date，source_date 在每条 claim 内部
3. **date 类型**：yaml 解析可能返回 datetime.date 对象，需转换为字符串
4. **不要过度标记矛盾**：timeframe-shift 和 cycle-shift 是正常变化，不是错误
5. **durable rule 门槛**：不要将所有方法论都推入 framework，只有真正改变操作纪律的才进
6. **用户确认**：标记 true-conflict 时必须高亮提醒用户，不要自行裁决
7. **技术教学内容 vs 操作纪律**：博主的技术教学（如长红线、K线形态、布林线）属于工具层知识，与操作纪律（仓位管理、买卖规则）不同。技术教学首次出现时留在 wiki 层，只有被多次验证、形成明确交易规则后才进入 framework。不要因单次技术课程就推入 framework。
8. **周期调整 vs 逻辑证伪**：当博主说某方向"调整一段时间""规避"时，要区分是 cycle-shift（阶段性调整，后期可能回归）还是 logic-broken（逻辑证伪，永久失效）。前者不标记 claims 过期，后者才标记 superseded。半导体从"接棒主线"到"规避"属于 cycle-shift，claims 保持 active。
9. **双轨制对 Review 的影响**：轨道B（技术课程）的 claims 不参与 drift 分析。详见【文档分层与总纲更新规则】→【双轨制】章节。
10. **持仓更新完整pipeline**：当用户要求"更新持仓"时，执行完整pipeline：①读取当前positions.yaml和watchlist.yaml → ②获取实时行情计算PnL → ③交叉引用claims判断持仓逻辑是否变化 → ④更新positions.yaml（含closed_positions记录）→ ⑤更新watchlist.yaml today_snapshot → ⑥输出持仓总结+操作建议。不要只改一个文件。
11. **操作建议必须关联claims**：给出操作建议时，必须引用具体的claim ID（如claim-20260531-002-a）和博主判断依据，不是拍脑袋建议。

### Review 输出要求

- 结论前置：先给 3-5 条核心结论
- 结构化：分主题、分日期、分变化类型
- 量化：提供 claim 数量、比例、分布
- 区分事实与判断：明确哪些是 claim 原文，哪些是 review 的分析判断

---

## 文档分层与总纲更新规则

学习新 raw 时按以下层级沉淀，不要把单日盘面直接写成长期方法论：

1. `sources/raw/财经`：保留原始内容或整理稿，作为可回溯证据。
2. `knowledge/claims`：抽取带 source path、evidence quote、scope、confidence 的观点卡。
3. `knowledge/wiki/每日复盘`：沉淀单日盘面、早午晚盘判断和案例。
4. `knowledge/wiki/市场分析`、`knowledge/wiki/投资方法论`：沉淀可复用专题，如指数、量能、主线、仓位、做T、科创虹吸。
5. `framework`：只写跨阶段可复用、可验证、可执行的 durable rule。
   - `framework/*.md`（如 `stock-analysis-playbook.md`、`market-cycle-framework.md` 等）：市场认知层的可执行框架
   - `framework/trading-rules.md`：**交易规则手册**——聚焦具体操作纪律（选股规则、买卖点、套利策略、风控线），与 methodology 层的市场判断框架分离
6. `knowledge/wiki/投资方法论/博主方法论总纲.md`：最高层小白教材和导航页，只吸收已经被多篇 raw 或多个市场阶段验证过的稳定框架。

### 双轨制：市场认知层 vs 操作工具层

博主内容分为两个轨道，沉淀路径不同：

**轨道A：市场认知层（大方向思路）**
- 来源：每日早盘/午盘/复盘/动态
- 内容：市场周期、主线判断、板块扩散、资金行为、情绪周期
- 特点：随市场变化，需要持续更新，有保质期
- 沉淀：claims → wiki → methodology → framework

**轨道B：操作工具层（技术分析课程）**
- 来源：视频课程（技术分析第一课/第二课/...）
- 内容：K线形态、技术指标、量价分析、支撑压力、买卖纪律
- 特点：一旦学会永久有效，不随市场变化
- 沉淀：直接进 `framework/technical-analysis-framework.md` 和 `methodology/technical-analysis.md`

**技术课程处理规则**：
- 识别 source_type = `video-course` 或 `technical-lesson` 的内容
- 技术教学内容不进入 `claims/`（因为不是"观点"是"知识"）
- 技术教学内容直接进入 `framework/technical-analysis-framework.md` 和 `methodology/technical-analysis.md`
- 若需标记 claim，使用 `claim_type: technical-knowledge`，`timeframe: permanent`
- **⚠️ 混合内容分离规则**：当单篇 raw 同时包含轨道A（行情观点）和轨道B（技术教学）时，必须拆分为**两个独立的 claim 文件**（`-001.yaml` 轨道A + `-002.yaml` 轨道B），不能混在同一文件。详见 `references/mixed-content-ingestion.md`
- **技术知识不需要"多次提及"才进 framework** — 与轨道A的 durable rule 标准不同，技术工具是正规金融学内容，一旦教学即可沉淀
- **技术工具不进总纲** — `博主方法论总纲.md` 只放市场认知层的稳定框架，具体K线形态/指标公式进 `technical-analysis-framework.md`
- **交易规则进 trading-rules.md** — 具体操作纪律（如接力标的选择、尾盘套利法、买卖点条件）属于可执行规则，进 `framework/trading-rules.md`，不进 `technical-analysis-framework.md`
- **旧 claims 清理**：若历史 claims 中已有技术课程内容（如 `claim_type: technical-signal` 的长红线定义），应将其改为 `technical-knowledge` 并标记 `status: superseded`，链接到 `technical-analysis-framework.md`
- **课程进度表禁止编造**：只列出已实际发布的课程。未发布的统一写"后续课程 ⬜ 待博主更新"，可注明博主提到的大方向，但必须标注"推测，非已确认"。禁止编造"第二课：长黑线"等具体名称。
- **轨道B文件结构**：
  ```
  framework/technical-analysis-framework.md    ← 可执行 playbook（操作规则表、风控线、课程进度）
  framework/trading-rules.md                   ← 交易规则手册（选股规则、买卖点、套利策略、接力方法论）
  methodology/technical-analysis.md           ← 方法论沉淀（原理、适用场景、与轨道A协作）
  knowledge/wiki/投资方法论/技术分析.md        ← 知识库层（详细展开，持续更新）
  ```
  四层内容互补：framework 给规则，trading-rules 给操作纪律，methodology 给原理，wiki 给细节。

**双轨制对 Review 的影响**：
- 轨道B（技术课程）的 claims 不参与 drift 分析（`timeframe: permanent`，无保质期）
- 轨道A（市场认知）的 claims 正常参与 drift、contradiction、supersedes 分析
- Review 报告中的"主题漂移"和"矛盾识别"只针对轨道A claims
- 技术 claims 在 Review 中仅做存在性检查（是否已正确标记为 `technical-knowledge` 并链接到 framework）

**双轨制对 qing-stock-analysis 的影响**：
- 检索 claims 时区分市场认知 vs 技术工具：`claim_type: technical-knowledge` 属于永久有效的技术分析知识，与市场周期/板块判断类 claims 分开引用
- 技术 claims 只作为工具引用，不用于判断当前市场方向

**双轨制对 qing-methodology-review 的影响**：
- 技术 claims（`claim_type: technical-knowledge`）不参与 drift 分析
- 不标记为 contradiction 或 expiration
- 详见 `references/dual-track-compatibility.md`

总纲不是每次学习都必须更新。只有满足以下任一条件时才更新总纲：

- 新观点跨多篇 raw 反复出现，并且能解释不同交易日或不同市场环境。
- 新观点改变核心框架，如周期定位、主线判断、个股分类、仓位管理、交易纪律。
- 新观点补齐总纲缺失模块，并且已经有足够案例支撑。
- 原有总纲表述过窄、过时或与最新稳定框架存在冲突，需要修订。

以下内容不要直接进入总纲：

- 单日指数点位、某天早盘剧本、尾盘临时操作。
- 只依赖一条消息催化、尚未验证持续性的题材。
- 只适用于某只个股或某个短线窗口的策略。
- 与旧观点冲突但还没有足够样本确认的新判断。
- **技术课程中的具体工具**（如长红线定义、布林线公式）——这些进 `technical-analysis-framework.md`，不进总纲。
- **具体操作纪律**（如接力标的选择方法论、尾盘套利法）——这些进 `framework/trading-rules.md`，不进总纲。

每次 Learning Update Report 必须说明：

- 本次新增/更新了哪些 raw、claims、wiki、framework。
- `博主方法论总纲.md` 是否更新。
- **Agent prompt 同步状态**：如果更新了涉及输出格式规范的 framework 文件，是否同步更新了 `prompts/system/market_analysis_framework.txt`。
- 如果总纲或 prompt 没有更新，说明原因，例如"本次为单日盘面案例，尚未满足总纲级沉淀条件"或"本次为技术课程，已更新 technical-analysis-framework，不涉及大盘分析格式规范，无需更新 prompt"。

## 禁止事项

- 不用脚本替代 LLM 判断方法论变化。
- 不把单日语境直接提升为长期 framework。
- 不创建没有 source path 和 evidence quote 的 claim。
- 不删除旧观点；冲突观点使用 supersedes 或 contradicts 连接。
- **不要遗漏专题 wiki 更新**：更新每日复盘 wiki 的同时，检查 claim 涉及的主题（如端侧AI、AIPC、超级电容、MLCC等）是否已有独立专题 wiki 页面。若该主题跨多篇 raw 出现但无专题页，用户可能会追问"XX方向没有整理吗？"——应在 ingestion 阶段主动检查并创建/更新专题页，不要只更新每日复盘。

## 学习索引 (Learn Index)

追踪所有 raw 文档的学习状态，避免重复处理或遗漏。

### 索引文件

- **位置**：`knowledge/learn-index.md`
- **生成方式**：自动化脚本扫描 `sources/raw/财经/`、`sources/processed-log.md` 和 `knowledge/claims/`
- **更新时机**：每次完成一批文档的 qing-learning 流程后，或用户要求时

### 索引结构

```markdown
# 学习索引 (Learn Index)

> 生成时间: 2026-05-29 01:00
> 总文档: 448 | 已学习: 448 | 未学习: 0 | 学习率: 100.0%

---

## 图例
- ✅ = 已学习（已提取claims或已记录processed-log）
- ⬜ = 未学习（仅整理为raw，未提取claims）

---

## 2026-05-28 ✅ (8/8)

- ✅ [动态] 动态：26-05-28：4050支撑确认与情绪拐点.md
- ✅ [视频] 动态：26-05-28：产业逻辑视频计划与观察标的.md
- ...
```

### "已学习"判定标准

一个 raw 文档被认定为"已学习"，当且仅当满足以下任一条件：

1. **在 `sources/processed-log.md` 中有记录** — 表示已完成完整的 qing-learning 流程（raw → claims → wiki → framework）
2. **在 `knowledge/claims/*.yaml` 中被引用** — 表示已提取 claims（可能通过其他路径，如批量处理）

**判定逻辑**：
```python
# 伪代码 — 双重验证确保100%覆盖
processed_raws = set()   # 从 processed-log.md 提取
claim_raws = set()       # 从所有 claims/*.yaml 的 source_path 提取
all_learned = processed_raws | claim_raws  # 并集
```

### 为什么需要双重验证

- `processed-log.md` 是人工/LLM 记录的处理日志，可能遗漏某些通过批量脚本处理的文档
- `knowledge/claims/*.yaml` 是自动生成的结构化数据，包含 `source_path` 字段指向原始 raw 文档
- 两者交叉验证可确保 100% 覆盖，避免"以为没学实际已学"或"以为学了实际没学"

### 与 processed-log.md 的关系

| 文件 | 用途 | 更新时机 |
|------|------|---------|
| `processed-log.md` | 记录每次 qing-learning 的详细处理过程（claims ID、wiki 更新、framework 变更） | 每次处理完一篇 raw 后手动/自动追加 |
| `learn-index.md` | 汇总所有 raw 文档的学习状态，便于快速查看哪些已学、哪些未学 | 定期批量生成（如每天结束时）或用户要求时 |

两者互补：processed-log 是"过程记录"，learn-index 是"状态快照"。

### 生成脚本要点

```python
# 核心逻辑
for date in sorted_dates:
    files = date_files[date]
    learned_count = sum(1 for f in files if f in all_learned)
    status_icon = "✅" if learned_count == len(files) else "🔄" if learned_count > 0 else "⏳"
```

### 常见陷阱

1. **仅检查 processed-log 会漏判** — 某些文档可能通过批量脚本直接生成 claims，未记录到 processed-log
2. **仅检查 claims 会误判** — 某些旧文档可能有 claims 但未更新 wiki/framework，学习不完整
3. **日期解析不一致** — raw 文件名中的日期格式可能为 `26-05-28` 或 `2026-05-28`，需统一处理
4. **文档类型标注** — 根据文件名关键词自动分类（复盘/早盘/午盘/视频/动态/研报/周复盘）

## 已知问题与解决

### 手动录入流程（用户直接提供博主内容）

**场景**：用户直接转述或粘贴博主评论/动态内容（如"UP在注意仓位里评论说..."），要求补充到文档并学习。这不是来自 fetch 脚本的自动抓取，而是用户手动提供的内容。

**流程**：
1. **确认日期和类型**：根据内容判断日期（如"今天下午"=今天）和文档类型（动态/早盘/午盘/复盘/视频）。
2. **规范化命名**：按项目命名规则 `类型：YY-MM-DD：简短描述.md`（如 `动态：26-05-29：注意仓位评论-跟指数动的票.md`）。
3. **写入 frontmatter**：包含来源、日期、类型等元信息。
4. **结构化正文**：保留原文引用（`> ` 块引用），添加解读要点分层。
5. **保存到 `sources/raw/财经/`**：使用 `write_file` 创建文件。
6. **走完整 qing-learning 流程**：
   - 抽取 claims（至少包含原文 evidence_quote、interpretation、confidence）
   - 更新相关 wiki 页面
   - 更新 claims/index.md
   - 更新 knowledge/wiki/log.md
   - git add + commit
7. **Learning Update Report**：说明新增 raw、claims、wiki 更新、framework/总纲是否更新。

**注意事项**：
- 不要假设用户提供的日期是系统当前日期。用户可能引用历史内容。
- 用户转述的内容可能不完整，尽量保留原话，缺失部分标注"[用户转述]"或"[原文]"区分。
- 如果用户只提供了一句话（如本次 session 的 UP 评论），claims 数量可以精简（2-3 条），不必强行拆成 5-6 条。
- 手动录入的 raw 文件同样要遵守"单日盘面不直接写成长期方法论"的分层规则。
- **优先处理文档，后改脚本**：当用户同时要求"补充到文档"和"改脚本"时，先完成文档录入和 qing-learning 流程，再处理脚本修改。用户明确偏好"先不改脚本，先处理文档"。
- **用户直接提供 UP 评论/动态内容时**：如果用户说"UP在注意仓位里评论说..."，先确认该内容是否已被之前的 fetch 脚本自动抓取（检查 `sources/raw/财经/` 和 `sources/original/bilibili/`）。如果已存在，不要重复创建 raw 文件，直接走 qing-learning 流程即可。如果不存在，按手动录入流程保存为 raw 后再走流程。

### B站评论提取：只保留UP主自己的评论

**核心规则**：只保存UP主（青枫浦上Q）自己的评论，其他用户评论一律忽略。不区分"置顶"还是"普通回复"。

**用户纠正历程**（重要，避免重复错误）：
1. 最初脚本回退到热评（第一条热评）→ 用户纠正："这两次拉取的动态置顶评论都是错的，动态没有置顶评论，只是截图的第一条"
2. 改为只检查 `upper.top`（真正置顶）→ 用户纠正："不是置顶只要是青枫浦上Q的就行，把置顶的逻辑删了吧，减少逻辑"
3. 最终简化：遍历 `replies` 找UP主评论，不区分置顶/普通

**最终逻辑**（`fetch_up_comment()`）：
```python
UP_NAME = "青枫浦上Q"

# 1. 先检查 upper.top（UP主置顶评论）
upper_top = data.get("data", {}).get("upper", {}).get("top")
if upper_top and upper_top.get("member", {}).get("uname") == UP_NAME:
    return {...}

# 2. 遍历 replies 找UP主自己的普通评论
for reply in data.get("data", {}).get("replies", []):
    if reply.get("member", {}).get("uname") == UP_NAME:
        return {...}

# 3. 没有找到UP主评论 → 不写评论部分
return None
```

**常见错误**：
- ❌ 回退到热评（`replies[0]`）→ 会抓到其他用户的热评（如 `oo魔人布欧oo`）
- ❌ 只检查 `upper.top` → 会漏掉UP主没有置顶的普通回复
- ❌ 在文档中标注"置顶评论"→ 应标注为"评论"或"UP主评论"

**文档标注规范**：
- 有UP主评论时：`### 评论` 或 `### 评论提示`
- 无UP主评论时：不写评论章节
- 不要写 `### 置顶评论`（除非确认是真正的UP置顶）

### 实时行情获取（持仓更新用）

**场景**：更新持仓或观察池时需要获取A股实时行情计算PnL。

**推荐数据源**：腾讯财经API（`https://qt.gtimg.cn/q=`）
- 稳定、无需认证、支持批量查询
- 格式：`v_sh600246="1~万通发展~600246~最新价~昨收~开盘..."`
- 编码：GBK，需 `decode('gbk', errors='replace')`

**用法示例**：
```python
import subprocess, re

result = subprocess.run(
    ['curl', '-s', 'https://qt.gtimg.cn/q=sh600246,sz000969'],
    capture_output=True
)
data = result.stdout.decode('gbk', errors='replace')

for line in data.split(';'):
    match = re.search(r'v_\w+="([^"]+)"', line)
    if match:
        parts = match.group(1).split('~')
        code, name, latest, prev = parts[2], parts[1], float(parts[3]), float(parts[4])
        change = round((latest - prev) / prev * 100, 2)
```

**备选**：新浪财经API（`https://hq.sinajs.cn/list=`）
- 可能返回403 Forbidden，不稳定
- 需添加Referer头：`curl -s -H 'Referer: https://finance.sina.com.cn' ...`

**注意事项**：
- 腾讯API返回的字段用 `~` 分隔，字段顺序固定
- 关键字段索引：2=代码, 1=名称, 3=最新价, 4=昨收, 5=开盘, 33=最高, 34=最低
- 计算盈亏时用最新价和成本价对比，不是用涨跌额
- 获取失败时（网络问题）应提示用户，不要编造数据

### 录音转文字文档的错别字修正

**场景**：用户提供录音转文字的原始文档（如充电视频语音转录），要求按项目 raw 格式整理并修正错别字。

**流程**：
1. 先确认文档是否已存在于 `sources/raw/财经/` 中（可能已被之前的 qing-learning 流程处理过）
2. 检查 git 历史确认文档状态
3. **逐段阅读全文**，标记所有疑似转录错误的地方
4. **并行交叉验证**（三条路径同时进行）：
   - **B站动态索引**：检查 `sources/original/bilibili/index.md`，搜索同期动态标题中的股票名（如 "星环科技拉直线"）。UP 当天可能为该标的单独发动态，这是最高置信度的验证来源
   - **本地知识库**：搜索 `sources/raw/财经/`、`knowledge/claims/`、`knowledge/wiki/`，用 UP 之前视频中明确提到过的方向/标的来反推（如 "卖枕头的" → 搜索 "枕头/家纺/睡眠" → 定位 5/30 视频 → 确认罗莱生活）
   - **UP 术语体系**：项目中有 UP 专有术语（如 "二轨" = 七轨布林线第二轨 MID+1×DEV，"蓝筹" 可能被转录为 "老灯"），参考 `methodology/technical-analysis.md` 和已有 claims/wiki
5. **逻辑一致性检查**：不要盲信转录文字。若一句话在逻辑上不通（如 "外盘不崩则国内好不到哪去"），应反向思考正确含义（"外盘崩了则国内更扛不住"），并向用户确认
6. **输出纠错对照表**：在 raw 文档中附 `转录纠错对照表`，列出 转录名→纠正名→代码→核实方式
7. 修正后走完整 qing-learning 流程（raw → claims → wiki）
8. 提交并推送

**关键 Pitfalls**：
- **不要只改错别字而不验证逻辑**：语音转录可能产生看似通顺但含义完全相反的句子
- **优先用 B站动态标题验证股票名**：UP 经常在股票异动时发单独动态（如 "XX拉直线的原因"），这是最直接的验证源
- **UP 术语体系**：以下为常见转录错误对照：
  - "二鬼/二轨" → 七轨布林线第二轨（MID+1×DEV），非 20 日均线
  - "老灯股" → 蓝筹股
  - "micc" → MLCC（多层陶瓷电容）
  - "六分" → 六氟磷酸锂
- 用户说"修正错别字"时，只做最小修改，不要改变文档结构或重新生成内容
- 修正后询问是否需要提交推送

### 本地项目 skill 与全局 skill 不同步

用户项目 `~/learning-investment-strategies/skills/qing-learning/SKILL.md` 包含更详细的工作流和规则。执行 qing-learning 任务时：

1. 先尝试读取本地项目 skill（`skill_view` 可能找不到，因为 skill 在项目目录内）。
2. 如果 `skill_view` 失败，直接用 `read_file` 读取 `~/learning-investment-strategies/skills/qing-learning/SKILL.md`。
3. 以本地项目 skill 为准，本全局 skill 仅作为 fallback。

### Claim schema 验证

Claim 文件必须满足 `src/qing_investment/claim_schema.py` 中的字段和枚举要求。生成 claims 后建议用项目内验证脚本检查：

```bash
cd ~/learning-investment-strategies && python3 -m pytest tests/test_claim_schema.py -v
```

### 重复处理已存在的文档

**问题**：用户要求处理一篇 raw 文档时，该文档可能已经被之前的 qing-learning 流程处理过（已创建 claims、已更新 wiki）。重复处理会浪费时间并可能产生冲突。

**解决**：处理前先检查文档是否已存在：

1. 检查 `sources/raw/财经/` 目录下是否已有同名或同日期文件
2. 检查 git 历史：`git log --all --oneline -- "sources/raw/财经/文件名.md"`
3. 检查 `knowledge/claims/` 中是否已有对应日期的 claim 文件
4. 检查 `knowledge/wiki/每日复盘/` 中是否已有对应日期的 wiki

如果文档已存在且已处理，直接告知用户当前状态，询问是否需要：
- 重新处理（覆盖旧 claims/wiki）
- 仅修正原文错别字
- 跳过

**避免过度探索 git 历史**：确认文档存在后，无需反复用 `git diff` 或 `git show` 查看完整历史，避免触发上下文压缩。

### Pipeline QA：检查 original → raw 迁移遗漏

**场景**：用户询问 "哪些 original/bilibili 文档还没整理到 raw/下" 或类似 pipeline 遗漏检查。

**错误做法（不要这样做）**：
- 只比较文件名/标题
- 只按日期前缀匹配
- 假设相同日期 = 同一篇内容

**正确做法**：
1. 列出 `sources/original/bilibili/` 下目标日期的所有文件。
2. 读取每个 original 文件的 **内容**（不只是标题），提取唯一标识：
   - `dynamic_id`（frontmatter 中的 canonical ID）
   - 原文中的 **独特短语/关键句**（如 "4055差了5个点"、"子弹留好，等黄金坑"）
3. 用这些唯一标识去 `sources/raw/财经/` 中 grep 搜索：
   - 先搜 `dynamic_id`
   - 再搜 2-3 个独特短语
4. 如果 **没有任何标识命中**，则判定为未整理。
5. 输出结果时区分：
   - 已整理（有命中）
   - 未整理（无命中）
   - 重复抓取（同一 `dynamic_id` 多个 original 文件，仅 fetch_time 不同）

**为什么必须读内容**：
- Bilibili 动态可能在同一天发布多篇（早盘、午盘、盘中、收盘后）。
- 同一 `dynamic_id` 可能被多次抓取（不同 fetch_time），产生多个 original 文件但只对应一篇 raw。
- 文件名中的标题片段可能因截断而不匹配 raw 中的重命名标题。
- 部分 original 文件是 **纯图片动态**（无文字），只有 OCR 内容或截图，标题无法反映实质内容。

**重复抓取的根因与修复**：
- 若发现同一 `dynamic_id` 有多个 original 文件（仅 `fetch_time` 不同），说明抓取脚本的去重逻辑失效。
- 常见原因：v1 脚本（`fetch_bilibili_up.py`）使用 `last_dynamic_id` 单条判重，而非 `processed_ids` 集合判重。手动运行 v1 会绕过 v2 的集合判重，导致重复。
- **修复**：统一使用 v2（`bilibili_notify.py` 或 `fetch_bilibili_up_v2.py`），删除或禁用 v1；或给 v1 也加上 `processed_ids` 集合判重。
- **清理**：保留 `fetch_time` 最早的文件，删除重复抓取的后续文件。

**参考实现**：见 `references/pipeline-qa-dedup.md`。

### B站动态脚本版本统一与重复清理

**场景**：用户发现 `sources/original/bilibili/` 下有重复抓取的动态文件（同一 `dynamic_id`，不同 `fetch_time`），或评论提取结果错误（抓到了其他用户的热评而非UP主评论）。

**根因**：项目同时存在 v1（`fetch_bilibili_up.py`）和 v2（`fetch_bilibili_up_v2.py` / `bilibili_notify.py`）两个抓取脚本。v1 使用 `last_dynamic_id` 单条判重，v2 使用 `processed_ids` 集合判重。手动运行 v1 会绕过 v2 的集合判重，导致重复。

**额外陷阱——同名脚本文件路径优先级（已修复）**：
- `~/.hermes/scripts/` 和 `~/learning-investment-strategies/scripts/` 下可能各有一份 `fetch_bilibili_up_v2.py`
- `bilibili_notify.py` 通过 `sys.path.insert(0, ...)` 优先加载**同目录下的旧版本**，导致UID、函数、逻辑不一致
- 旧版 `fetch_bilibili_up_v2.py` 有 `fetch_top_comment()`（不验证用户名，无 `upper.top` 时回退到 `replies[0]`）
- 新版 `fetch_bilibili_up_v2.py` 有 `fetch_up_comment()`（只返回 `uname == UP_NAME` 的评论）
- **后果**：旧版会抓到其他用户的热评（如"妖夢大人"），写入文档后污染 claims

**修复步骤**：
1. **修改导入逻辑**（推荐）：修改 `~/.hermes/scripts/bilibili_notify.py`，优先从项目目录加载：
   ```python
   REPO_ROOT = Path(os.environ.get("HERMES_REPO_ROOT", "/home/ubuntu/learning-investment-strategies"))
   sys.path.insert(0, str(REPO_ROOT / "scripts"))
   sys.path.insert(1, str(Path(__file__).resolve().parent))
   ```
2. **同步函数名**：`bilibili_notify.py` 导入的必须是 `fetch_up_comment`（验证用户名），而非 `fetch_top_comment`（不验证用户名）
3. **删除旧版脚本**：`rm ~/.hermes/scripts/fetch_bilibili_up_v2.py`（避免函数名不一致导致 ImportError，同时防止未来误加载）
4. **统一使用 v2**：cron 任务和手动运行都使用 `bilibili_notify.py`
5. **清理重复文件**：按 `dynamic_id` 分组，保留 `fetch_time` 最早的文件，删除后续重复

**验证修复是否成功**：
```bash
# 1. 确认旧版已删除
ls ~/.hermes/scripts/fetch_bilibili_up_v2.py 2>&1  # 应报 No such file

# 2. 确认 bilibili_notify.py 导入正确
grep "fetch_up_comment\|fetch_top_comment" ~/.hermes/scripts/bilibili_notify.py
# 应只看到 fetch_up_comment

# 3. 测试运行，检查评论是否正确
python3 ~/.hermes/scripts/bilibili_notify.py 2>&1 | head -20
```

### 测试验证要求

用户要求修改/删除/清理文件后，必须执行验证测试：
1. 检查操作结果（如 `ls`、计数）
2. 确认唯一性/完整性（如 dynamic_id 去重验证）
3. 运行相关脚本确认功能正常（如 `build_index()`）
4. 简要汇报测试结果

---

### Git 协作：远程分支合并与结构性差异分析

**场景**：用户要求"拉取远程分支"或"同步最新改动"，但本地有未提交修改，或远程与本地存在结构性差异（如 YAML 配置文件的列表项增减、格式风格不同）。

**执行流程**：
1. **查看远程分支状态**：`git log --oneline master..origin/master` 确认远程领先多少 commit
2. **尝试直接合并**：`git merge origin/master --no-commit --no-ff`
   - 若成功 → 检查 `git diff --cached --stat` 了解变更范围
   - 若失败（"local changes would be overwritten"）→ 进入冲突解决流程
3. **冲突解决**：
   - `git stash` 暂存本地改动
   - `git merge origin/master --no-commit --no-ff` 预览合并结果
   - 检查关键文件差异（如 `git diff --cached -- config/stock_monitor/watchlist.yaml`）
   - `git merge --abort` 中止预览合并
   - `git stash pop` 恢复本地改动
4. **结构性差异分析**（YAML/JSON 配置文件）：
   - 行级 `git diff` 可能因格式风格不同（引号、缩进）而噪音巨大
   - 使用 Python + `yaml`/`json` 解析后比较数据结构：
     ```python
     import yaml, subprocess
     remote_raw = subprocess.check_output(['git', 'show', 'origin/master:config/file.yaml']).decode()
     remote = yaml.safe_load(remote_raw)
     with open('config/file.yaml') as f:
         local = yaml.safe_load(f)
     remote_ids = {t['id'] for t in remote.get('themes', [])}
     local_ids = {t['id'] for t in local.get('themes', [])}
     print('Remote only:', sorted(remote_ids - local_ids))
     print('Local only:', sorted(local_ids - remote_ids))
     ```
   - 这种分析能准确识别：列表项增减、字段缺失、嵌套结构变化
5. **决策**：
   - 若远程版本更新、更完整 → `git checkout -- <file>` 放弃本地版本，再 `git merge origin/master`
   - 若本地版本包含重要未同步数据 → 手动合并（提取本地独有数据，追加到远程版本）
   - 若差异仅为格式风格 → 统一为远程风格
6. **合并后验证**：
   - `python -c "import yaml; yaml.safe_load(open('config/file.yaml'))"` 确认 YAML 有效
   - 运行项目验证脚本（如 `stock_monitor.py --status`）

**关键 pitfall**：
- 不要直接 `git pull` 而不先检查本地改动状态——可能覆盖重要未提交数据
- 不要仅依赖 `git diff` 行级输出来判断 YAML 配置差异——格式风格变化会淹没实质内容变化
- 合并后不要忘记 `git merge --abort` 清理预览合并状态——残留 merge state 会阻塞后续操作
- 对于 `watchlist.yaml` 这类频繁更新的文件，远程版本通常包含更新的市场数据，优先接受远程版本

---

### Git 协作：拉取优先与冲突解决

**场景**：用户在本地做了修改（如生成了新的 claims、更新了 wiki），同时远程仓库也有新提交（如另一台设备或之前会话推送的内容）。直接操作可能导致冲突或覆盖。

**纪律**：
1. **任何修改前先拉取**：`git pull` 或 `git fetch + git merge`
2. **如果有本地未提交改动**：先 `git stash`，拉取后再 `git stash pop`
3. **stash pop 产生冲突时**：
   - 不要自动接受任意一方
   - 先检查冲突文件的内容差异
   - 对 claims：检查暂存文件与远程文件是否是**同一来源**（同一 raw 文档）还是**不同来源**
   - 对 wiki：合并不同段落，保留双方的有效内容
   - 对 index.md：手动合并索引条目，确保不遗漏

**冲突解决检查清单**：
- [ ] 暂存的 claim 文件与远程同名文件是否内容相同？→ 若是，删除暂存版本
- [ ] 暂存的 claim 文件与远程同名文件是否来源不同？→ 若是，重命名暂存文件（如 `claim-YYYYMMDD-003.yaml` → `claim-YYYYMMDD-005.yaml`）
- [ ] 暂存的 claim 观点是否已存在于远程其他 claim 文件中？→ 用 grep 搜索关键短语确认
- [ ] wiki 文件冲突是否是同一日期的不同整理方式？→ 手动合并段落
- [ ] 解决后验证：`git diff --stat` 确认修改合理

**为什么重要**：知识库是增量沉淀的，覆盖或丢失 claims 会导致后续分析引用错误观点，wiki 冲突未妥善解决会导致索引断裂。

---

### 观察池量化策略更新（Observation Pool Quant Update）

**场景**：用户要求"将观察池策略写到量化配置里"、"更新观察池"、"修改操作量化策略"。

**涉及文件**：
- `config/stock_monitor/watchlist.yaml` — 观察池主题和个股
- `config/stock_monitor/strategy_pack.yaml` — 量化策略框架
- `config/stock_monitor/positions.yaml` — 仓位配置

**执行流程**：
1. **拉取最新数据**：运行 `stock_monitor.py --live-analysis-context` 获取观察池所有标的实时行情
2. **数据分析**：基于收盘/实时数据，计算每只标的涨跌幅、上影线/下影线比例、板块内联动情况
3. **板块强度排序**：按组内平均涨幅、领涨标的表现、联动程度排序
4. **量化介入点计算**：涨停/大涨标的等分歧回踩，温和上涨等分时均线，弱势暂不参与
5. **更新三个配置文件**：同步更新 watchlist、strategy_pack、positions
6. **Git 提交**：`git add config/stock_monitor/ && git commit && git push`

**介入点计算规则**：
- 涨停(≥9.5%)：等分歧回踩，介入区间为今日低点 ~ 实体中位
- 大涨(5-9.5%)：等分歧，介入区间为今日低点 ~ 开盘价
- 小涨(0-5%)：分时均线附近，收盘价×0.98 ~ 收盘价
- 收跌/大跌：暂不参与，等企稳信号

**仓位分配原则**：
- 第一优先级板块：总仓位3-4成，单标的不超过2成
- 第二优先级板块：总仓位2-3成
- 第三优先级板块：总仓位1-2成
- 规避方向：0仓位
- 空仓可上5成，满仓应降仓留空间

**关键发现必须记录**：
- 组内是否联动（如万通涨停但得润大跌 = CPU链证伪）
- 大涨标的是否有长上影线（抛压信号）
- 板块与大盘/防御的相对强弱

#### Themes 管理纪律（用户硬性要求）

**核心规则**：观察池 themes **如果不是用户明确说要移除的，每次应该都是新增，不是直接替换**。

这意味着：
- 更新 watchlist 时，新 theme 应该**追加**到现有 themes 列表末尾
- 旧 theme 只有在用户明确说"删除/移除/替换 XXX"时才删除
- 不要假设用户想要"清空旧 themes 只保留新的"——即使市场环境变化，旧 themes 也应保留作为观察锚
- **用户主动发现 themes 缺失时**：按历史恢复流程补回，不要只解释原因

**恢复被误删 themes 的方法**：
1. 查看 git 历史：`git log --oneline --all -- config/stock_monitor/watchlist.yaml`
2. 提取历史 themes 列表：`git show <commit>:config/stock_monitor/watchlist.yaml | grep "^  - id:"`
3. 对比当前 themes 与历史 themes，找出缺失的
4. 从历史版本提取缺失 theme 的完整 YAML 块
5. **追加到当前文件末尾（保持现有 themes 不动）**
6. 更新 `updated_at` 字段
7. **验证**：运行 `python -m qing_investment.stock_monitor --status` 确认无报错

**常见错误**：
- ❌ 用新 themes 直接替换整个 themes 列表 → 丢失历史观察锚
- ❌ 重构观察池时"清空"旧 themes → 违反用户 append-only 要求
- ❌ 用户要求恢复 themes 时只给说明不动手 → 用户要求直接执行
- ✅ 新 theme 追加，旧 theme 保留，除非用户明确说移除
- ✅ 用户说"恢复"时立即执行恢复流程，不额外解释

---

### 用户直接提供 UP 评论时的处理流程

**场景**：用户直接转述 UP 在某条动态下的评论内容（如"UP在注意仓位里评论说..."），要求"补充到文档里并学习"。

**关键判断**：
1. **先检查是否已自动抓取**：读取 `sources/raw/财经/` 和 `sources/original/bilibili/` 中对应日期的文件，确认该评论是否已被 fetch 脚本捕获。检查方法：
   - 按日期列出 raw 和 original 文件
   - 读取内容，搜索用户提供的评论中的**独特短语**（如"跟着指数涨的"、"赚钱效应起来了"）
   - 如果找到匹配，说明已自动抓取，直接走 qing-learning 流程（抽取 claims、更新 wiki）
   - 如果没找到，按手动录入流程创建 raw 文件

2. **区分"补充到文档"和"跟指数动的票有哪些"**：
   - "补充到文档" = qing-learning 流程（raw → claims → wiki）
   - "跟指数动的票有哪些" = 数据查询任务（运行 stock_monitor.py 获取实时行情，计算各标的与指数的相关系数或当日涨跌幅对比）
   - 两个任务**不要混为一谈**，先完成文档录入，再执行数据查询

3. **Claim 抽取要点**：
   - UP 评论通常较短（1-3 句话），claims 数量精简为 2-3 条
   - 必须包含 evidence_quote（原文引用）
   - interpretation 要区分"事实判断"（今天跟指数涨的票表现好）和"操作建议"（没跟指数动的不要碰）
   - 如果评论涉及具体标的（如"半导体""券商"），在 claim 的 tags 中标注

**常见错误**：
- ❌ 不检查就创建新 raw 文件 → 导致重复
- ❌ 把数据查询任务和文档录入任务混在一起 → 输出混乱
- ❌ claims 强行拆成 5-6 条 → 过度拆分，失去重点
- ❌ 忽略用户同时要求的"看观察池" → 遗漏第二个任务

---

### Patch/编辑前必须完整读取文件

**场景**：使用 `read_file` 读取大文件时设置了 `offset`/`limit` 参数（分页读取），随后对该文件执行 `patch` 操作时失败。

**错误表现**：
```
patch failed: Could not find a match for old_string in the file
Did you mean one of these sections?
_warning: ... was last read with offset/limit pagination (partial view). 
Re-read the whole file before overwriting it.
```

**根因**：`patch` 工具需要完整文件内容来定位匹配字符串，但分页读取只加载了部分内容，导致匹配失败。

**正确做法**：
1. 如果文件之前是用 `offset`/`limit` 读取的，**在 patch 前必须重新完整读取**：`read_file(path)`（不带 offset/limit）
2. 或者，如果确定只需要修改文件末尾附近的内容，可以先用 `read_file(path, offset=N)` 定位到目标区域，读取足够上下文后再 patch——但前提是匹配字符串在已读取的范围内
3. 对于大文件（>500行），如果修改位置明确在文件尾部，可以先用 `tail -n 50` 或 `read_file(path, offset=总行数-50)` 读取尾部，然后 patch

**最佳实践**：
- 小文件（<500行）：始终完整读取后再 patch
- 大文件（>500行）：先用 `search_files` 或 `grep` 定位目标字符串所在行号，然后 `read_file(path, offset=行号-20, limit=50)` 读取足够上下文，确认匹配字符串完整可用后再 patch
- 如果 patch 失败后提示 partial read，立即完整读取文件再重试

### YAML 特殊字符转义（Claim 文件编写）

**场景**：claim 的 `interpretation` 或 `evidence_quote` 字段包含中文引号、冒号、特殊标点时，YAML 解析可能报错。

**错误示例**：
```yaml
interpretation: "更好确定点"的含义——①...②...
```
YAML 解析器会将 `"更好确定点"` 后的中文字符视为标量延续，遇到 `：` 或 `"` 时解析失败。

**正确做法**：
1. **避免在 YAML 值中使用中文引号 `""` 和 `''`**。改用描述性语言：
   ```yaml
   interpretation: 更好确定点的含义——①今日情绪拐点已出现，但尚未经受过考验；②...
   ```
2. **若必须引用原文**，使用单引号包裹整个值，内部双引号不转义：
   ```yaml
   evidence_quote: '"没有让各位抄底也是鉴于今晚美股的情况..."'
   ```
3. **避免值内出现未转义的 `:` 后跟空格**。YAML 会将其解析为键值对分隔符。若原文含 `：` 后空格，用引号包裹整个值。
4. **验证习惯**：每次生成 claim YAML 后，运行项目内验证脚本确认格式正确：
   ```bash
   cd ~/learning-investment-strategies && python3 -c "
   import yaml, sys
   sys.path.insert(0, 'src')
   from qing_investment.claim_schema import validate_claim_dict
   with open('knowledge/claims/claim-YYYYMMDD-NNN.yaml') as f:
       data = yaml.safe_load(f)
   for claim in data['claims']:
       validate_claim_dict(claim)
       print(f'OK: {claim[\"id\"]}')
   "
   ```

**为什么重要**：claim 文件是知识沉淀的核心载体，YAML 格式错误会导致后续自动化流程（索引生成、wiki 链接、矛盾检测）全部中断。生成时多花 30 秒验证，避免后续数小时的排查。
