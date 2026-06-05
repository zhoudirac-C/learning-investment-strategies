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

## Layer 3: 动态应用层（已实现，2026-06-05）

### 集成方式：Prompt 工程（在 `market_analyst()` 中注入）

**实现位置**：`src/qing_investment/agent/graph/nodes.py`

**数据流**：
```
用户提问 "今天MLCC板块怎么看？"
    ↓
_extract_themes_from_state(state)
    ├─ query 关键词匹配 _THEME_KEYWORD_MAP
    ├─ claims subject 字段匹配
    └─ sector_context name 匹配
    → 提取主题集合 {"MLCC", "被动元件"}
    ↓
_load_reasoning_patterns(state)
    ├─ 加载 framework/reasoning-patterns.yaml
    ├─ 与 applicable_themes 取交集
    ├─ 按匹配主题数排序
    └─ 取 Top 3（控制 prompt 长度）
    ↓
market_analyst() context["reasoning_patterns"]
    → 注入到 LLM prompt，与 framework_rules 并列
    ↓
LLM 按推理模式 step 顺序执行分析
```

**匹配机制**：`_THEME_KEYWORD_MAP` 定义了关键词→主题映射（位于 nodes.py），扩展新主题时需同步更新。

**Prompt 指令**：`market_analyst.txt` 中新增【推理模式使用规则】，强制 Agent：
- 按推理模式步骤顺序思考
- 用 risk_factors 检查证伪条件
- 用 confidence_indicators 标注高置信信号
- 实时数据与推理模式矛盾时以实时数据为准

### 抽取工具

`scripts/extract_reasoning_patterns.py` 支持 `--dry-run` / `--single` / `--max` / `--incremental` 四种模式。
详见 `references/reasoning-pattern-extraction-workflow.md`。

## 实施路线图

### Phase 1：抽取首批推理模式 ✅（已完成 2026-06-05）

1. **选取经典案例**：MLCC周期（2篇 raw）、Rubin BOM拆解、主线切换判断
2. **手动拆解推理链**：4 条模式写入 `framework/reasoning-patterns.yaml`
3. **Agent 集成**：`nodes.py` 中增加 `_load_reasoning_patterns()`，`market_analyst.txt` 增加推理模式使用规则
4. **批量抽取脚本**：`scripts/extract_reasoning_patterns.py` 支持增量/批量/单篇模式

### Phase 2：验证与迭代（进行中）

1. **对比测试**：同一行情，分别用"无推理模式"和"有推理模式"的 prompt，看 AI 输出差异
2. **收集反馈**：用户判断哪个更像 UP 的风格
3. **迭代完善**：补充遗漏的推理步骤、修正风险因素

### Phase 3：自动化抽取（已部分实现）

1. **批量脚本已就绪**：`scripts/extract_reasoning_patterns.py` 可后台批量处理 469 个候选文件
2. **增量模式可用**：`--incremental` 跳过已处理文件，断点续跑
3. **持续扩展**：新 raw 学习后运行 `--incremental --max 5` 增量抽取

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
