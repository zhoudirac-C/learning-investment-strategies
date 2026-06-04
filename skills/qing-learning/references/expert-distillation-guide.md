# 专家思维蒸馏指南 (Expert Distillation Guide)

> 用途：当用户询问"如何让AI像UP主一样思考""蒸馏一个人的投资思维""AI模仿UP主分析"时使用。
> 状态：与项目现有 `sources → claims → wiki → methodology → framework → skills` 链路互补，不是替代。

## 核心概念

"蒸馏一个人"在AI领域通常叫 **Character/Expert Distillation**，目标是让模型学会特定人的：
1. **知识**（知道什么）→ 项目已有：`knowledge/claims/` + `knowledge/wiki/`
2. **思维模式**（怎么推理）→ **需要补充**：推理模式抽取 + 思维链模板。详见 `references/reasoning-pattern-architecture.md`（含YAML模板、三层架构、实施路线图）。
3. **表达风格**（怎么说）→ **需要补充**：风格语料库
4. **决策偏好**（怎么选）→ **部分已有**：`framework/` 中的 durable rules

## 三条实现路径

### 路径一：Prompt Engineering + RAG（项目当前最接近）

**原理**：不改变模型权重，通过 system prompt + 检索知识库让模型"扮演"UP主。

**当前状态**：项目已有 `qing-learning` 知识沉淀链路，但缺少：
- **推理模式库**：UP是怎么从A推到B的（不只是结论）。详见 `references/reasoning-pattern-architecture.md` 中的YAML模板和Layer 2实现。
- **风格约束**：UP的典型表达、口头禅、句式
- **多轮记忆**：让AI记住之前对某票/板块的判断和修正

**具体加强动作**：
1. **抽取"推理模式"而非仅"观点"**
   - 现有 claims：`国产算力是主线`（观点）
   - 应增加：UP是怎么得出这个结论的？
     - 看了哪些信号？（量能、涨停家数、资金流入）
     - 排除了哪些干扰？（券商护盘≠主线切换）
     - 置信度如何变化？（从观察到确认的过程）
   - 沉淀位置：`framework/reasoning-patterns.yaml`（详见 `references/reasoning-pattern-architecture.md` 中的YAML模板）

2. **建立"思维链模板"**
   ```
   当UP分析一个板块时，他的思考顺序是：
   ① 先看指数位置和量能 → ② 看板块涨停梯队 → ③ 看核心票承接 → ④ 判断是主升还是补涨 → ⑤ 决定仓位
   ```
   把这个变成 `framework/` 里的**结构化推理模板**，而不是零散规则。详见 `references/reasoning-pattern-architecture.md`。

3. **增加"风格样本"**
   - 收集UP的典型表达方式（如"先买后卖做T"、"大级别调整没完"）
   - 在 `qing-stock-analysis/SKILL.md` 的输出约束中增加**风格约束**

### 路径二：Fine-tuning（真正的"蒸馏"）

**原理**：用UP主的内容作为训练数据，微调小模型，让它内化UP的思维模式。

**技术方案**：

| 方案 | 工具 | 成本 | 效果 |
|------|------|------|------|
| LoRA/QLoRA微调 | Unsloth, Axolotl | 低（消费级GPU） | 风格+知识部分内化 |
| 全参数微调 | 需要A100/H100 | 高 | 效果最好但没必要 |
| 蒸馏到小模型 | 用GPT-4/Claude生成"UP风格回答"，训练小模型 | 中 | 适合部署 |

**数据格式**（需要准备）：
```json
{
  "instruction": "分析今天CPO板块的走势",
  "input": "2026-05-28早盘：CPO板块高开低走，中际旭创跌2%...",
  "output": "【UP风格回答】CPO今天这个走法，先别慌。关键看中际旭创的承接...",
  "reasoning": "UP判断板块的核心逻辑是：①核心票是否破位 ②量能是否萎缩 ③是否有新催化..."
}
```

**关键挑战**：
- 需要**大量"问题-UP回答"对**（至少几百条）
- 当前470篇raw是**单向输出**（UP的观点），缺少**问答对**
- 解决方案：用GPT-4/Claude模拟"如果UP被问到XX，他会怎么回答"

### 路径三：Agent + Memory（最符合项目架构）

**原理**：不微调模型，构建**有长期记忆、能反思、能修正**的Agent。

**架构升级**：
```
用户提问
  ↓
Agent 检索知识库（claims/wiki/cases）← "知识"
  ↓
Agent 加载"思维模式模板" ← "怎么思考"
  ↓
Agent 执行推理（多步思考）← "推理过程"
  ↓
Agent 输出"UP风格回答" ← "表达"
  ↓
用户反馈 → 更新记忆 ← "持续学习"
```

**需要增加的组件**：

| 组件 | 作用 | 放在项目哪里 |
|------|------|-------------|
| **推理模式库** | UP的典型推理链条 | `framework/reasoning-patterns/` |
| **风格语料库** | UP的典型表达 | `knowledge/wiki/博主/表达风格.md` |
| **对话记忆** | 记住之前的判断和修正 | 新增`memory/`或利用现有`cases/` |
| **反思机制** | 判断自己的分析是否符合UP框架 | 在`qing-methodology-review`中扩展 |

## 推荐的最小可行路径（MVP）

基于现有项目，建议按这个顺序：

### Phase 1：强化现有RAG（1-2周）
1. **抽取"推理模式"**
   - 从470篇raw中，找出UP分析市场/板块/个股的**固定套路**
   - 沉淀到 `framework/reasoning-patterns.md`

2. **建立"风格约束"**
   - 收集UP的口头禅、典型句式
   - 加到 `qing-stock-analysis/SKILL.md` 的输出约束里

3. **增加"多轮记忆"**
   - 让AI记住之前对某只股票/板块的判断
   - 在 `cases/` 里建立"判断-验证"闭环

### Phase 2：构建训练数据（2-4周）
1. **生成问答对**
   - 用现有raw + claims，让GPT-4生成"如果UP被问到XX，他会怎么回答"
   - 格式化为instruction-following数据集

2. **尝试LoRA微调**
   - 用Unsloth或Axolotl，在7B-13B模型上做QLoRA
   - 目标不是替代大模型，而是做一个"UP风格专用小模型"

### Phase 3：Agent化（持续）
1. **引入反思机制**
   - 分析完成后，让Agent自问："这个判断符合UP的框架吗？"
   - 不符合时，检索相关claims进行修正

2. **引入预测-验证闭环**
   - Agent给出判断后，记录到 `cases/`
   - 后续验证，更新方法论权重

## 关键问题与风险

| 问题 | 说明 |
|------|------|
| **数据质量** | 470篇raw足够"知识"，但缺少"问答对"和"推理过程" |
| **时效性** | UP的观点随市场变化，AI需要知道"什么时候的观点" |
| **幻觉风险** | AI可能编造UP没说过的话，必须严格引用claims |
| **过度拟合** | 微调可能让AI只会模仿，不会适应新情况 |

## 与现有项目架构的关系

```
现有链路：Raw → Claims → Wiki → Methodology → Framework → Skills
                    ↑
            新增：推理模式抽取（从Claims中提炼"怎么推理"）
                    ↑ 详见 references/reasoning-pattern-architecture.md
            新增：风格语料（从Raw中提炼"怎么说"）
                    ↑
            新增：Cases闭环（判断→验证→修正）
```

**不冲突**：distillation不是替代现有链路，而是在现有知识沉淀基础上，增加"思维模式"和"表达风格"两层能力。具体实现方法（YAML模板、三层架构、实施路线图）详见 `references/reasoning-pattern-architecture.md`。
