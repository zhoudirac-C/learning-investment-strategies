# 推理模式架构与模板 (Reasoning Pattern Architecture)

> 用途：当用户要求"让AI像UP主一样思考""蒸馏UP的投资思维"时，指导如何从现有知识库构建可执行的推理模式层。
> 与 `references/expert-distillation-guide.md` 的关系：distillation-guide 讲三条技术路径（Prompt/RAG/Fine-tune/Agent），本文件讲**具体的推理模式层架构**和**YAML模板**。

## 三层架构

基于现有 `qing-learning` 链路（raw → claims → wiki → framework → skills），增加**推理模式层**：

```
Layer 1: 知识库层（已有）
    Raw → Claims → Wiki
    存储：UP知道什么（观点、事实、判断）

Layer 2: 推理模式层（需要新增）
    从UP的分析实例中抽取"怎么推理"
    存储：UP是怎么从A推到B的（思维链、决策树、排除法）

Layer 3: 动态应用层（需要开发）
    将推理模式与实时数据结合
    存储：Agent如何调用推理模式、如何验证、如何修正
```

## Layer 2: 推理模式的具体实现

### 什么是推理模式

不是"UP看好MLCC"（这是观点/claim），而是：

```
UP是怎么得出"看好MLCC"的？
  ① 观察到涨价公告（事实）
  ② 结合MLCC在AI服务器的用量数据（知识）
  ③ 对比历史周期（存储、硅片的规律）
  ④ 判断资金认可度（龙头是否涨停、是否连续放量）
  ⑤ 给出操作建议（等分歧回踩，不追高）
```

### 推理模式 YAML 模板

```yaml
# framework/reasoning-patterns.yaml
reasoning_patterns:
  - pattern_id: "upstream_price_cycle"
    name: "上游涨价周期确认"
    description: "当上游材料/元件出现涨价信号时，UP判断周期位置的推理链"
    applicable_themes:
      - "mlcc"
      - "存储"
      - "硅片"
      - "被动元件"
    triggers:              # 什么信号触发这个推理模式
      - "产品涨价公告"
      - "产能利用率提升"
      - "龙头公司订单饱满"
    reasoning_chain:       # UP的推理步骤（按顺序）
      - step: 1
        name: "确认涨价真实性"
        checks:
          - "是否全行业涨价，还是个别公司？"
          - "涨价是否可持续（产能约束 vs 临时供需）？"
          - "是否有官方公告或产业链验证？"
        evidence_sources:
          - "公司公告"
          - "产业链调研"
          - "行业协会数据"
      - step: 2
        name: "计算下游需求弹性"
        checks:
          - "下游主要应用领域（AI服务器/新能源车/消费电子）"
          - "各领域的增量空间（百分比或绝对值）"
          - "需求增长是否匹配涨价幅度"
        evidence_sources:
          - "下游客户 capex 计划"
          - "机构预测报告"
      - step: 3
        name: "对比历史周期位置"
        checks:
          - "类比哪个历史周期（存储/硅片/MLCC上一轮）"
          - "当前处于周期的哪个阶段（底部/启动/加速/见顶）"
          - "与历史周期的差异（新变量是什么）"
        evidence_sources:
          - "历史价格数据"
          - "历史 claims（同主题过去判断）"
      - step: 4
        name: "判断资金认可度"
        checks:
          - "是否有龙头涨停或连续放量"
          - "板块内是否联动（非单票脉冲）"
          - "与大盘/防御板块的相对强弱"
        evidence_sources:
          - "实时行情（涨停家数、量能）"
          - "板块涨幅排名"
      - step: 5
        name: "给出操作建议"
        checks:
          - "当前位置是否适合介入（启动期/加速期/尾声）"
          - "介入方式（直接买/等分歧回踩/等回调）"
          - "仓位建议（核心仓位/试探仓位/不参与）"
        action_template: "等分歧后缩量回踩，不追连续加速"
    risk_factors:          # 哪些情况会证伪这个推理
      - "涨价被证伪（官方辟谣/产能快速释放）"
      - "大盘系统性风险（指数大跌>3%）"
      - "情绪退潮（板块涨停家数骤减）"
      - "下游需求不及预期"
    confidence_indicators: # 哪些信号增加置信度
      - "多家公司同步涨价"
      - "龙头连续涨停且板块联动"
      - "机构研报密集覆盖"
    related_claims:        # 关联的 claims（用于RAG检索）
      - "claim-20260528-001"
      - "claim-20260529-003"
    related_wiki:          # 关联的 wiki 专题
      - "knowledge/wiki/市场分析/MLCC产业链.md"
```

### 推理模式与现有项目结构的映射

| 推理模式字段 | 映射到现有项目 | 说明 |
|-------------|---------------|------|
| `triggers` | `watchlist.yaml` 的 `buy_setup` | 触发条件对应观察池买入条件 |
| `reasoning_chain` | 新增 `framework/reasoning-patterns.yaml` | 目前项目没有这层 |
| `risk_factors` | `watchlist.yaml` 的 `invalidation_setup` | 买点失效条件 |
| `related_claims` | `knowledge/claims/*.yaml` | 通过 claim ID 关联 |
| `related_wiki` | `knowledge/wiki/` | 通过文件路径关联 |
| `action_template` | `strategy_pack.yaml` 的 `position_rules` | 操作建议模板 |

## Layer 3: 动态应用层

### 如何将推理模式注入 AI 分析

**方案A：Prompt工程（轻量，推荐先实现）**

修改 `stock_monitor.py` 的 `format_agent_analysis_context()`：

```python
# 在生成分析上下文时，根据触发的主题附加相关推理模式
if trigger.theme_id in reasoning_patterns:
    context += f"\n\n[推理模式：{pattern.name}]\n"
    for step in pattern.reasoning_chain:
        context += f"{step.step}. {step.name}：{'；'.join(step.checks)}\n"
    context += f"\n风险因素：{'；'.join(pattern.risk_factors)}\n"
```

AI 收到上下文后，会"模仿"UP的推理方式输出分析。

**方案B：RAG检索（中等）**

1. 将推理模式向量化（与 claims/wiki 一起）
2. 当监控触发某主题时，检索该主题的推理模式
3. 将检索结果作为 context 给 AI

**方案C：Fine-tune（重量，长期）**

需要准备训练数据：
```json
{
  "instruction": "分析今天MLCC板块的走势",
  "input": "2026-06-04：风华高科+3.81%，三环集团+2.1%，洁美科技+1.5%...",
  "output": "【UP风格】MLCC今天这个走法，先确认涨价真实性...",
  "reasoning": "upstream_price_cycle: ①涨价公告已确认 ②AI服务器需求弹性大 ③类比存储周期启动期 ④风华高科放量突破..."
}
```

## 实施路线图

### Phase 1：抽取首批推理模式（1-2周）

1. **选取经典案例**：从470篇raw中，找出UP对3-5个经典板块/主题的分析完整过程
   - 候选：MLCC周期、CPU自研链、光互连、超级电容、存储周期
2. **手动拆解推理链**：按上述YAML模板，逐条填写
3. **创建 `framework/reasoning-patterns.yaml`**
4. **修改 `stock_monitor.py`**：在 `format_agent_analysis_context()` 中根据主题附加推理模式

### Phase 2：验证与迭代（2-4周）

1. **对比测试**：同一行情，分别用"无推理模式"和"有推理模式"的prompt，看AI输出差异
2. **收集反馈**：用户判断哪个更像UP的风格
3. **迭代完善**：补充遗漏的推理步骤、修正风险因素

### Phase 3：自动化抽取（长期）

1. **从raw中自动识别分析段落**：用NLP或规则提取UP的"因为...所以..."句式
2. **自动归类到推理模式**：将新分析映射到已有模式，或创建新模式
3. **持续更新**：随着UP内容增加，推理模式库自动扩展

## 与现有技能的衔接

| 现有技能 | 如何衔接推理模式 |
|---------|-----------------|
| `qing-stock-analysis` | 在分析个股/板块时，加载相关推理模式作为prompt的一部分 |
| `qing-stock-monitor-update` | 更新观察池时，根据推理模式的 `triggers` 和 `risk_factors` 调整 `buy_setup`/`invalidation_setup` |
| `qing-methodology-review` | Review时检查推理模式是否与最新claims一致，标记过时的模式 |
| `qing-learning` | Ingestion时，除了抽取claims，还要识别是否涉及新的推理模式 |

## 常见陷阱

1. **混淆"观点"和"推理"**：`"UP看好MLCC"` 是观点，应该进 claims；`"UP是怎么得出看好MLCC的"` 是推理，应该进 reasoning-patterns
2. **过度泛化**：一个推理模式只适用于特定类型的主题（如涨价周期），不要试图用一个模式覆盖所有情况
3. **忽略时效性**：推理模式中的 `evidence_sources` 和 `related_claims` 需要定期更新，否则AI会用过期信息推理
4. **与现有规则重复**：`risk_factors` 和 `invalidation_setup` 可能重叠，保持同步更新
