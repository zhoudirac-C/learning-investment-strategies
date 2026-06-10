---
name: qing-methodology-review
description: |
  Use when: user asks for "qing review", "方法论复盘", "review claims", "检查一致性" or similar requests.
  周期性检查 claims、wiki、methodology 和 framework，识别长期方法论变化、矛盾、过期观点和需要人工确认的问题。
---

# qing-methodology-review

## 目标

周期性检查 claims、wiki、methodology 和 framework，识别长期方法论变化、矛盾、过期观点和需要人工确认的问题。

## 跨 Skill 兼容性说明

qing-learning 采用**双轨制**架构（市场认知层 vs 操作工具层），这对下游 skill 有明确影响：

| 下游 Skill | 影响 | 处理方式 |
|-----------|------|---------|
| `qing-stock-analysis` | 检索 claims 时需区分市场认知 vs 技术工具 | 技术 claims 只作为工具引用，不用于判断当前市场方向 |
| `qing-methodology-review` | 技术 claims 不参与 drift/contradiction 分析 | 跳过 `claim_type: technical-knowledge` 且 `timeframe: permanent` 的 claims |
| `stock-research-engine` | 无直接影响 | 通用个股研究工具，不依赖 qing-learning claims |
| `valuation-analysis` | 无直接影响 | 基于《股市真规则》方法论，独立于博主内容体系 |

详见 `references/dual-track-compatibility.md`。

## 触发条件

- 用户说 "qing review"、"方法论复盘"、"review claims"
- 用户要求检查某段时间的 claims 一致性
- 用户发现矛盾或观点变化，要求分析
- 周期性方法论 review（默认最近7天，可指定日期范围/主题/claim ID）

## 必读参考

1. `framework/methodology-review-protocol.md`
2. `framework/contradiction-policy.md`
3. `skills/qing-methodology-review/references/methodology-review-protocol.md`
4. `skills/qing-methodology-review/references/contradiction-policy.md`
5. `skills/qing-methodology-review/references/review-report-template.md`
6. `skills/qing-methodology-review/references/review-execution-script.py` — 辅助分析脚本

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

- 读取窗口内所有 claim 文件（含 B站动态等非传统 source_type）
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
| agent-up-conflict | **Qing-Agent 分析 vs UP 观点矛盾（2026-06-10 新增）** | 检查知识库是否完整→补 claims→重新分析；若仍矛盾→UP 优先 |
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

## 关键 Pitfalls

1. **YAML 解析错误**：部分 claim 文件有格式问题（如特殊字符未转义），跳过错误文件继续分析，不要中断
2. **source_date 位置**：claim 文件根级可能没有 source_date，source_date 在每条 claim 内部
3. **date 类型**：yaml 解析可能返回 datetime.date 对象，需转换为字符串
4. **不要过度标记矛盾**：timeframe-shift 和 cycle-shift 是正常变化，不是错误
5. **durable rule 门槛**：不要将所有方法论都推入 framework，只有真正改变操作纪律的才进
6. **用户确认**：标记 true-conflict 时必须高亮提醒用户，不要自行裁决
7. **技术教学内容 vs 操作纪律**：博主的技术教学（如长红线、K线形态、布林线）属于工具层知识，与操作纪律（仓位管理、买卖规则）不同。技术教学首次出现时留在 wiki 层，只有被多次验证、形成明确交易规则后才进入 framework。不要因单次技术课程就推入 framework。
8. **周期调整 vs 逻辑证伪**：当博主说某方向"调整一段时间""规避"时，要区分是 cycle-shift（阶段性调整，后期可能回归）还是 logic-broken（逻辑证伪，永久失效）。前者不标记 claims 过期，后者才标记 superseded。半导体从"接棒主线"到"规避"属于 cycle-shift，claims 保持 active。
9. **双轨制对 Review 的影响**：轨道B（技术课程）的 claims 不参与 drift 分析。详见 `references/dual-track-compatibility.md`。
10. **持仓更新完整pipeline**：当用户要求"更新持仓"时，执行完整pipeline：①读取当前positions.yaml和watchlist.yaml → ②获取实时行情计算PnL → ③交叉引用claims判断持仓逻辑是否变化 → ④更新positions.yaml（含closed_positions记录）→ ⑤更新watchlist.yaml today_snapshot → ⑥输出持仓总结+操作建议。不要只改一个文件。
11. **操作建议必须关联claims**：给出操作建议时，必须引用具体的claim ID（如claim-20260531-002-a）和博主判断依据，不是拍脑袋建议。

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
