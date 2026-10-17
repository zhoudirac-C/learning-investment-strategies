# 技术方案：gator pattern 演进管线 —— 每周推理模型驱动的规则库更新

> 状态：**草案，未实施**（等拍板）
> 日期：2026-10-17
> 触发：用户指出「claim 保真门禁只解决提取层保真，无法更新 55 章规则」——
>       本方案补 **claims → pattern 层** 的回流通道。
> 关联：
> - `docs/analysis/gator-extraction-method-vs-ours-20261016.md`（A1-A5 对照）
> - `docs/analysis/claim-fidelity-gate-design-draft-20261016.md`（claim 层保真，互补不重叠）
> - `docs/design/dual-school-architecture.md`（双学派架构，§3.2 P3 拆解）

---

## 〇、结论前置

1. **缺口已实证**：`reasoning-patterns-gator.yaml`（50 条 pattern）由
   `build_gator_patterns.py` 于 2026-10-15 **一次性**从冻结的 GitHub 镜像生成，
   输入写死为 `sources/third_party/gator-method/03-规则体系/`，**无增量、无 cron、
   无 diff 机制**。每日新增的鳄鱼文章只进 claims 层（当前 gator claims 仅 11 条），
   **规则库是死的**。
2. **本方案补一条周度回流管线**：每周一次，用**推理模型**把本周新增 gator claims
   逐条归因为「强化既有 pattern / 矛盾修正 / 新主题候选」三类，产出 review 报告。
3. **默认影子模式**：管线**只出报告，不改 yaml**。pattern 库的每一次实际变更都经
   人工确认（沿用 framework-maintenance 提案制与 gator 草案「需人工 review」的既有门禁）。
4. **这同时就是"得出我们自己的方法"的载体**：原作者的 55 章是他从 711 篇文章提炼的
   静态快照；本管线让我们**从原文流中自行持续提炼/修正规则**，随着时间推移，
   `reasoning-patterns-gator.yaml` 会从"他的镜像"演化为"我们验证过的版本"。
5. **前置依赖**：claim 层保真门禁（A2/A2b 草案）应先落地——垃圾 claim 进，
   垃圾 pattern 归因出。但两管线可并行开发，互不阻塞。

---

## 一、缺口定位（实证）

| 层 | 产物 | 输入 | 更新机制 | 状态 |
|---|---|---|---|---|
| Claim 层 | `knowledge/claims/claim-*.yaml`（gator 侧 11 条） | 每日公众号/B站原文 | ✅ 每日提取管线 + gate1-5 | 活的 |
| Pattern 层 | `framework/reasoning-patterns-gator.yaml`（50 条，generated_at 2026-10-15） | 冻结镜像 `sources/third_party/gator-method/03-规则体系/` | ❌ 一次性脚本 | **死的** |

实证依据：
- `build_gator_patterns.py` 第 34 行：`SRC_DIR = .../gator-method/03-规则体系`，无增量参数；
- yaml 头部自述：`provenance_note: 草案状态，触发条件/步骤为程序化摘录，需人工 review 后转正式库`；
- 消费侧 `nodes.py` 的 pattern_router 按 embedding 语义路由读该 yaml —— **不更新=路由语料永远停在 10-15**。

---

## 二、总体设计

### 2.1 架构图

```
每周新增 gator claims（school: gator，source_date 在窗口内）
        │
        ▼  Step 1（机械层，Python）：增量筛选 + 候选召回
        │    - state.json 记录已处理 claim id，只取新增
        │    - 每条 claim 与 50 条 pattern 做 embedding 相似度，取 top-3 候选
        │    - 本周新增 = 0 → 直接退出，不调 LLM（零成本空转）
        ▼
  Step 2（推理模型，每周一次）：逐条归因分类
        │    输入：claim（statement/evidence_quote/interpretation）
        │         + top-3 候选 pattern 全文（trigger/steps/thresholds）
        │    输出五分类：
        │      ① reinforce  强化既有 pattern（新例证/新日期）
        │      ② refine     修正既有 pattern（阈值调整/限定条件变化）
        │      ③ contradict 与既有 pattern 矛盾（学派内观点漂移）
        │      ④ new_theme  50 章未覆盖的新方法论主题
        │      ⑤ irrelevant 与规则层无关（行情描述/数据点评）
        ▼
  Step 3（机械层，Python）：聚合 → 周度报告
        │    reports/gator-pattern-evolution-YYYYMMDD.md
        │    【影子模式】到此为止，不写任何 yaml
        ▼
  人工 review 报告 → 拍板 → 执行写回（见 §四）
```

### 2.2 五分类的设计依据

- **①reinforce**：对应原作者 `[核心]/[次要]/[单源]` 的频次思想，但用**我们自己的语料**
  计数——一条 pattern 被不同日期的原文反复确认，证据强度上调（落地 A4 的
  `evidence_strength`，且数据来源可核）。
- **②refine**：鳄鱼本人会修正阈值/条件（如「止跌 5 信号」有 2024-11-18 与
  2025-09-19 两个版本，pattern ch01 的 source_dates 已体现）——refine 让规则跟随作者演进。
- **③contradict**：学派**内部**漂移，与 `school-conflicts.yaml`（跨学派）不同。
  处理方式沿用既有原则：**不自动裁决**，登记进报告，人审后决定 supersedes 或并列。
- **④new_theme**：原作者 55 章之外的新方法论——**这是我们独有的增量**，
  走 `framework/proposals/` 提案制（与 qing 学派同一门禁，≥2 个不同日期来源 +
  人审，比 qing 的 ≥4 周窗口略宽，理由：gator 日更频率高，窗口可缩短——**拍板项**）。
- **⑤irrelevant**：必须存在且默认偏向它——符合「宁可漏不可错」的信噪比原则，
  纯行情描述不得污染规则库。

---

## 三、关键实现要点

### 3.1 脚本与入口

| 项 | 值 |
|---|---|
| 项目脚本 | `scripts/evolve_gator_patterns.py`（新建） |
| cron 包装 | `~/.hermes/scripts/qing_gator_pattern_evolution.py`（thin wrapper，命名沿用既有约定） |
| 状态文件 | `infra/data/gator_pattern_evolution/state.json`（processed claim ids + last_run） |
| 报告 | `reports/gator-pattern-evolution-YYYYMMDD.md` |
| 频率 | 每周一次，建议**周日 21:30**（一周文章已齐；避开周五 22:37 方向跟踪与周六复盘） |
| 参数 | `--window 7d`（默认）/ `--dry-run` / `--since YYYY-MM-DD`（补跑） |

### 3.2 推理模型通道（用户拍板项）

用户明确要求每周跑**推理模型**。与 discover/chain_tracker 的 hermes_global 跟随策略不同，
本任务**模型应显式可配**：

- 脚本参数 `--model <provider:model>` 或环境变量 `GATOR_EVOLVE_MODEL`；
- 未指定时回落 hermes_global（跟随 `~/.hermes/config.yaml` model.default）；
- ⚠️ 已知坑（framework-maintenance skill 实测）：hermes_global 解析到 k3 时
  **仅允许 temperature=1**，llm_client 调用需按通道适配；
- 推理模型调用慢，但每周一次 + claim 量小（当前周增 10-20 条量级），成本可控。

### 3.3 保真约束（与 A2/A2b 联动）

Step 2 的 prompt 必须携带三条硬约束（继承 claim 保真门禁的思想）：

1. 归因结论必须引用 claim 的 `evidence_quote` 原文，不得凭 statement 二次推断；
2. ②refine 必须明确指出「原规则怎么说的 → 新文章怎么说的」两侧引文；
3. ④new_theme 必须给出 ≥1 条原文引文，且标注「仅 N 个来源日期」。

### 3.4 新主题候选的频次门槛

- 单篇文章孤立说法 → 进报告的「观察区」，**不提名**；
- 同一主题 ≥2 个不同 `source_date` 的 claim 命中 → 才生成提案草案落
  `framework/proposals/`（status: nominated，school: gator）；
- 提案转正仍走人审 8 步（framework-maintenance 既有清单），含重启 Agent 使
  `_PATTERNS_CACHE` 生效。

---

## 四、写回路径（人审通过后）

| 分类 | 写回动作 | 门禁 |
|---|---|---|
| ①reinforce | pattern 追加 `evidence_claims: [claim_id]`、`source_dates` 并集、`evidence_strength` 计数 +1 | 报告确认后脚本批量执行 |
| ②refine | pattern 的 trigger/thresholds 修订 + `evolution_log` 记一条（日期/claim_id/前后 diff） | **必须人工逐条确认** |
| ③contradict | pattern 标记 `drift_flag` + 报告双列呈现；supersedes 或并列由用户拍板 | **LLM 禁自动裁决** |
| ④new_theme | 提案落 `framework/proposals/`，走提案制 | 提案制既有门禁 |
| ⑤irrelevant | 无动作 | — |

写回统一由脚本执行（不改手写 yaml），每次写回后：
`version` 递增 + `evolution_log` 追加 + git commit。

---

## 五、与既有机制的关系（不重复造轮子）

| 既有机制 | 关系 |
|---|---|
| `qing-learning-review`（方法论复盘） | 复盘的是 **qing 学派** claims 一致性；本管线是 **gator 学派 pattern 层**，正交互补 |
| `extract_reasoning_patterns.py --incremental` | 填 qing 框架 examples；本管线是 gator 侧的对应物，但**多了归因分类与写回路径** |
| `framework/proposals/` 提案制 | ④new_theme 的出口，直接复用 |
| `school-conflicts.yaml` | 只管跨学派冲突；③是学派内漂移，不进该文件 |
| A2/A2b 保真门禁（草案） | **前置依赖**：保真门禁保 claim 质量，本管线保归因质量，两层串联 |
| 上游仓库重镜像 | 独立低频任务（跟踪「他的版本」），与本管线（提炼「我们的版本」）并行 |

---

## 六、风险与不确定性

1. **语义召回误判**：embedding top-3 可能漏掉正确 pattern → Step 2 prompt 允许
   LLM 声明「候选均不匹配」并自由归类，降低机械层误判的传导。
2. **refine/contradict 混淆**：作者「补充细节」与「改变观点」边界模糊 → 影子期
   重点观察这两类的准确率，误判率高则合并为一类「需人审修订」。
3. **样本稀疏期**：gator 断更或周增 claim 极少时，管线零成本空转（Step 1 退出），
   报告落「本周无新增」即可。
4. **影子期长度未定**：建议先跑 **4 周**影子模式，统计五分类的人工复核准确率，
   ≥90% 再开写回路径（拍板项）。
5. **50 条 pattern 本身还是草案**：provenance_note 声明「需人工 review 后转正式库」——
   本管线的 ②③ 写回客观上会推动这个 review 过程，但**首次全量人工 review 不在本
   方案范围**（可作为独立任务另行排期）。

---

## 七、实施 Phase（拍板后执行）

| Phase | 内容 | 产出 |
|---|---|---|
| P1 | `evolve_gator_patterns.py`：Step 1 增量筛选 + embedding 召回 + Step 3 报告骨架（Step 2 先 stub） | dry-run 可跑，报告出候选配对 |
| P2 | 接推理模型 Step 2（五分类 prompt + 保真约束）+ state.json | 首份完整周度报告 |
| P3 | 影子模式跑 4 周 → 人工复核准确率统计 | 准确率报告 + 是否开写回的决策依据 |
| P4 | 写回路径（§四）+ 提案制对接 + cron 上线 | 管线转正 |

---

## 八、决策点清单（供拍板）

| # | 事项 | 选项 |
|---|---|---|
| D1 | 整体方案是否批准 | 批准进 P1 / 修改后再议 |
| D2 | 推理模型选型 | 跟随 hermes_global / 显式指定（写具体模型） |
| D3 | 运行时间 | 周日 21:30（建议）/ 其他 |
| D4 | new_theme 提案门槛 | ≥2 个来源日期（建议）/ 沿用 qing ≥4 周窗口 |
| D5 | 影子期长度 | 4 周（建议）/ 其他 |
| D6 | 与 A2/A2b 的先后顺序 | 并行（建议，互不阻塞）/ 先 A2 后本方案 |
