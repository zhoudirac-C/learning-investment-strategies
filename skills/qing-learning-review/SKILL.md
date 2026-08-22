---
name: qing-learning-review
description: |
  方法论复盘 — 检查 claims 一致性、识别观点漂移、标记矛盾/过期。
  触发词：qing review、方法论复盘、review claims、检查一致性
---

# qing-learning-review

## 范围确定

- 默认：最近 7 天（含今天）
- 用户可指定：日期范围、特定主题、特定 claim ID

## 9 步复盘流程

### Step 1: 读取 Claims

```bash
grep "source_date:" knowledge/claims/claim-*.yaml | sort
```

提取：date, topic, text, claim_type, confidence, status, supersedes, contradicts

### Step 2: 统计分析

- 每日 claim 数量、主题分布（Top 20）
- claim_type 分布、confidence 分布、status 分布
- 有 supersedes/contradicts 的 claims

### Step 3: 主题漂移

| 变化类型 | 含义 |
|----------|------|
| no-change | 观点一致，重复确认 |
| clarification | 细化、补充条件 |
| extension | 扩展到新场景 |
| correction | 修正旧判断 |
| contradiction | 明确矛盾，需标记 |
| expiration | 观点过期 |

### Step 4: 矛盾分类

按 `framework/contradiction-policy.md`：

| 类型 | 含义 | 处理方式 |
|------|------|----------|
| timeframe-shift | 短期与长期视角不同 | 无需标记，说明时间维度 |
| cycle-shift | 市场阶段变化导致观点变化 | 标记为 cycle-shift，更新 status |
| logic-broken | 个股或板块逻辑被证伪 | 标记 contradicts，旧 claim 更新 status |
| risk-repriced | 宏观/流动性/风险偏好改变 | 标记 risk-repriced |
| agent-up-conflict | Agent 分析 vs UP 观点矛盾 | 检查知识库是否完整→补 claims→重新分析；若仍矛盾→**市场数据优先**（一级信息>二级>三级，价格/量能证据>任何观点——总计划 v2.1 第十一节），UP 观点仅作对照标签；无法裁决时标 true-conflict 高亮提醒用户 |
| true-conflict | 暂无清晰解释，需人工 review | 标记 true-conflict，高亮提醒用户 |

### Step 5: Durable Rule 筛选

**候选分流（v2.1 对齐，2026-08-10 起）**：durable rule 候选先分两类，去向不同——

| 类型 | 例子 | 去向 |
|------|------|------|
| A. 操作纪律类 | 买卖条件、仓位、风控线（如"赚20%砍半仓"） | 原 Review→Write 管道（见 qing-learning 总入口），写 `framework/trading-rules.md` 等 |
| B. 推理模式类 | 可复用的分析/推导步骤（如"涨价链五步拆解"） | **禁止直接写 framework 文档或 `framework/reasoning-patterns.yaml`**；生成模式提名提案 `framework/proposals/YYYYMMDD-<name>.yaml`，经市场验证 + 人审后才入库 |

**推理模式提名门槛**（三条同时满足，否则留在 wiki/claims 层继续观察）：

1. 提名复盘窗口 **≥4 周**（drift/矛盾复盘仍默认 7 天，两者解耦——模式提名需单独拉长窗口汇总）；
2. 同一逻辑在 **≥2 种市场阶段**（主升/震荡/调整/恐慌）对应的复盘内容中出现（防单 regime 过拟合）；
3. 提案附证据：每次出现的日期 + 当日市场阶段 + 原文摘录（source path + quote）。

**提名提案模板**（不用 `scripts/apply_pattern_proposal.py` 应用——该脚本只接受 validation 回填；人审通过后手工入库 `framework/reasoning-patterns.yaml`）：

```yaml
proposal_id: YYYYMMDD-pattern-nomination-<slug>
source: up-review
generated_at: '<ISO timestamp>'
status: pending-review   # pending-review → approved → applied | rejected
evidence:
  window: {start: 'YYYY-MM-DD', end: 'YYYY-MM-DD'}
  occurrences:
    - date: 'YYYY-MM-DD'
      regime: 震荡        # 主升/震荡/调整/恐慌
      source: <sources/raw/财经/ 或 sources/original/bilibili/ 下的 raw 文件路径>
      quote: "<原文摘录>"
candidate_pattern:
  pattern_id: <snake_case>
  name: <名称>
  description: <何时使用、解决什么问题>
  trigger: [<客观数据特征，不含"UP说">]
  data_requirements: [<每步所需数据及获取通道>]
  steps: [<推理步骤>]
  falsification: [<证伪条件>]
  validation:
    historical_hit_rate: null   # 入库前必须经回测/盲测回填
    applicable_regime: null
    known_failures: []
```

进 framework 条件（A 类操作纪律，满足其一）：
1. **明确规则**：有具体数字、条件、阈值（如"赚20%砍半仓"）
2. **多次重复**：同一方法论在不同日期出现 2 次以上
3. **解释旧冲突**：能解释之前矛盾的新规则
4. **改变操作纪律**：直接影响买卖/仓位/风控的决策规则
5. **例外条款**：**首次出现但直接影响当前持仓决策的操作纪律**，即使只出现1次也应进入 framework。例如：UP 说"能做T做T，反弹之后减仓，等黄金坑再补"——这是针对当前持仓的具体操作框架，不应等"出现2次"再采纳。判断标准：该规则是否直接回答了"现在怎么办"的问题？是→首次即入。
6. **方法论框架对比**：将本次 review 窗口内的 methodology claims（claim_type=methodology, timeframe=permanent）与 `framework/reasoning-patterns.yaml`、`framework/market-breadth-framework.md` 和 `knowledge/wiki/投资方法论/大盘分析方法论.md` 交叉对比。标记状态：已收录 / 新方法论 / 矛盾（需人工裁决）。矛盾归入 contradiction 分类处理。**新方法论属推理模式类——按上方提名门槛生成 proposals 提案，不再直接追加进 framework 文档。**

### Step 5.5: 批量提取推理模式（更新框架 examples）

review 窗口内若有新入库的 UP raw 文件（复盘/视频/专栏/产业链深度），运行批量提取，把推理链归入现有框架：

```bash
# 1. 预览：看哪些新文件会被处理（不提取不落盘）
.venv/bin/python scripts/extract_reasoning_patterns.py --incremental --dry-run

# 2. 确认后执行（LLM 提取 + 合并进 reasoning-patterns.yaml）
.venv/bin/python scripts/extract_reasoning_patterns.py --incremental

# 3. 窗口提取（推荐）：只处理复盘窗口内的新文件，避免历史 backlog 干扰
.venv/bin/python scripts/extract_reasoning_patterns.py --incremental --since $(date -d '14 days ago' +%F)
```

- 扫描范围（2026-08-22 起）：`sources/raw/财经/`（整理稿）**+ `sources/original/bilibili/`**（B站原始抓取，
  8 月起新内容直接落这里）。`--since` 按文件名 YYYY-MM-DD 前缀过滤，无日期前缀的文件在设置时被跳过。

- 作用：把新 raw 文件的推理链**合并进 `framework/reasoning-patterns.yaml` 现有框架的
  examples**（追加 example + 合并 themes/source_raw），是「更新框架」的批量路径。
- **框架不是定死的（2026-08-15 修正）**：脚本已改为**从 yaml 动态读框架列表**
  （`load_frameworks()`），新框架自动识别（现在 11 个，position_by_cycle 就是提案制新增的先例）；
  LLM 只能归入现有框架，**归不进去（落 others）就是「框架改造」信号**——打印 ⚠️ 提示，
  review 时应走提案制新增/改造框架。
- 与 Step 5 提案制的关系（两条路径互补，别混淆）：
  - **批量提取（本步）**＝内容填充：归入现有框架的 examples（不动框架结构、不新增框架）
  - **提案制（Step 5）**＝框架演进：新推理模式（现有框架装不下）→ `framework/proposals/` 提案 → 人审后入库
- 安全：`--incremental` 用 `.reasoning_extraction_state.json` 跳过已处理文件；合并是追加不覆盖；
  LLM 密集（每文件一次调用），按需运行、不挂 cron；窗口内无新 raw 文件则跳过本步。

### Step 6: 一致性检查

新 claims 与前期框架的冲突检查。

- **status 生命周期**：被 supersedes 的旧 claim 应落 `status: superseded`。机械回填已脚本化：
  `.venv/bin/python scripts/backfill_claim_status.py --dry-run` 预览后执行
  （contradicts 方向需人工裁决，脚本只列清单不自动翻转）。

### Step 7: 生成报告

输出格式参照最新一期复盘报告（`reports/methodology-review-*.md`，如 20260822 期），保存到 `reports/methodology-review-YYYYMMDD.md`

### Step 8: 提交

```bash
git add reports/methodology-review-YYYYMMDD.md
```

### Step 9: 汇报

核心结论（3-5条）+ 结构化数据 + 建议后续动作

## 关键坑

- 轨道B（technical-knowledge）不参与 drift 分析
- timeframe-shift 和 cycle-shift 是正常变化，不是错误
- durable rule 门槛要高，不要将单日观点推入 framework
- **用户确认**：标记 true-conflict 时必须高亮提醒用户，不要自行裁决
- **技术教学内容 vs 操作纪律**：博主的技术教学（如长红线、K线形态、布林线）属于工具层知识，与操作纪律（仓位管理、买卖规则）不同。技术教学首次出现时留在 wiki 层，只有被多次验证、形成明确交易规则后才进入 framework。不要因单次技术课程就推入 framework。
- **周期调整 vs 逻辑证伪**：当博主说某方向"调整一段时间""规避"时，要区分是 cycle-shift（阶段性调整，后期可能回归）还是 logic-broken（逻辑证伪，永久失效）。前者不标记 claims 过期，后者才标记 superseded。半导体从"接棒主线"到"规避"属于 cycle-shift，claims 保持 active。
- **双轨制对 Review 的影响**：轨道B（技术课程）的 claims 不参与 drift 分析。详见 `qing-learning` 总入口 skill 的跨 Skill 兼容性说明。
- **Review 后的 Framework 写入**：本 skill 是只读分析，但用户 workflow 通常要求 review 后将 durable rules 写入 framework。写入操作不属于本 skill 职责——详见 `qing-learning` 总入口 skill 的「Review→Write 工作流」章节。本 skill 的输出（报告 + durable rule 候选列表）是下游写入操作的输入。
- **推理模式类不走 framework 文档**：UP 复盘提炼出的分析/推导步骤是模式提名，必须走 `framework/proposals/` 提案制（门槛见 Step 5），经市场验证 + 人审后才入 `reasoning-patterns.yaml`。直接写入 = 绕过 validation，回 v2.0 老路。
  ⚠️ **例外（2026-08-15 用户拍板）**：`extract_reasoning_patterns.py --incremental`（Step 5.5）允许直接合并进 yaml——它只把新 raw 文件的推理链**追加为现有 10 框架的 examples**（不改框架结构、不新增框架），与提案制互补；新模式（现有框架装不下）仍走提案制。

## Skill 职责边界

本 skill 是**只读分析**：读 claims → 统计 → 漂移分析 → 矛盾识别 → 生成报告。
**不写 config、不给操作建议、不定义架构**。详见 `references/skill-scope-boundary.md`。
⚠️ **边界补充（2026-08-15 用户拍板）**：review 流程含 Step 5.5 批量提取推理模式——
那是「更新框架 examples」的 review 产出动作（用户明确「qing review 是更新框架的 skill」），
运行 `extract_reasoning_patterns.py --incremental` 属本 skill 职责；除此之外仍不写 framework。

## 历史合并记录

2026-06-10：`qing-methodology-review` 合并入本 skill。合并时遵循了**内容归属校验**原则——不属于方法论复盘的内容（持仓更新 pipeline、操作建议关联 claims、跨 Skill 架构定义）未迁移，只保留了矛盾分类、Durable Rule 筛选、主题漂移分析等核心复盘能力。详见 `references/skill-scope-boundary.md` 的「历史背景」章节。

## 自动化复盘脚本

⚠️ `scripts/methodology_review.py` **尚未实现**（references 里标注"待实现"），不要按上方命令调用。
周期性复盘目前按 9 步流程手工执行；`references/automated-review-script.md` 记录了手工流程的
脚本化参考（含 claims 读取/统计的代码片段与坑点），未来实现脚本时以它为基础。

## 输出要求

- 结论前置：先给 3-5 条核心结论
- 结构化：分主题、分日期、分变化类型
- 量化：提供 claim 数量、比例、分布
- 区分事实与判断：明确哪些是 claim 原文，哪些是 review 的分析判断

## 禁止事项

- 不用脚本替代 LLM 判断方法论变化。
- 不把单日语境直接提升为长期 framework。
- 不创建没有 source path 和 evidence quote 的 claim。
- 不删除旧观点；冲突观点使用 supersedes 或 contradicts 连接。
