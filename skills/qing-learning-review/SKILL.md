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

进 framework 条件（满足其一）：
1. **明确规则**：有具体数字、条件、阈值（如"赚20%砍半仓"）
2. **多次重复**：同一方法论在不同日期出现 2 次以上
3. **解释旧冲突**：能解释之前矛盾的新规则
4. **改变操作纪律**：直接影响买卖/仓位/风控的决策规则
5. **例外条款**：**首次出现但直接影响当前持仓决策的操作纪律**，即使只出现1次也应进入 framework。例如：UP 说"能做T做T，反弹之后减仓，等黄金坑再补"——这是针对当前持仓的具体操作框架，不应等"出现2次"再采纳。判断标准：该规则是否直接回答了"现在怎么办"的问题？是→首次即入。
6. **方法论框架对比**：将本次 review 窗口内的 methodology claims（claim_type=methodology, timeframe=permanent）与 `framework/market-breadth-framework.md` 和 `knowledge/wiki/投资方法论/大盘分析方法论.md` 交叉对比。标记状态：已收录 / 新方法论（建议追加）/ 矛盾（需人工裁决）。矛盾归入 contradiction 分类处理。若发现新方法论，在报告中标注"建议运行更新方法论"。

### Step 6: 一致性检查

新 claims 与前期框架的冲突检查。

### Step 7: 生成报告

输出格式见 `references/review-report-template.md`，保存到 `reports/methodology-review-YYYYMMDD.md`

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

## Skill 职责边界

本 skill 是**只读分析**：读 claims → 统计 → 漂移分析 → 矛盾识别 → 生成报告。
**不写 config、不给操作建议、不定义架构**。详见 `references/skill-scope-boundary.md`。

## 历史合并记录

2026-06-10：`qing-methodology-review` 合并入本 skill。合并时遵循了**内容归属校验**原则——不属于方法论复盘的内容（持仓更新 pipeline、操作建议关联 claims、跨 Skill 架构定义）未迁移，只保留了矛盾分类、Durable Rule 筛选、主题漂移分析等核心复盘能力。详见 `references/skill-scope-boundary.md` 的「历史背景」章节。

## 自动化复盘脚本

对于周期性复盘（如"review 过去14天"），可使用自动化脚本替代手工分析：

```bash
cd ~/learning-investment-strategies
python3 scripts/methodology_review.py --days 14 --output reports/methodology-review-$(date +%Y%m%d).md
```

脚本功能：
- 读取指定窗口内所有 claims
- 自动生成统计、主题漂移、矛盾分类、Durable Rule 候选
- 输出结构化报告（Markdown 格式）
- 自动 git add 报告文件

详见 `references/automated-review-script.md`。

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
