# 推理模式跨方向复用性指南

> 关联：`references/reasoning-pattern-extraction-workflow.md` §8（Phase 6 设计演进）、`references/reasoning-pattern-architecture.md`（三层架构）
> 用途：当用户质疑"推理模式是否只能针对单一方向"或"通用框架是否足够通用"时，引用本文档。

## 核心结论

**通用框架的 `examples` 列表天然支持跨方向复用。**

10 个通用框架（如 `upstream_cycle`、`mainline_identification`）是**推理骨架**，`examples` 是**不同主题下的具体应用**。同一骨架可以支撑 MLCC、PCB、存储、硅片、有色、化工等不同方向的分析。

## 为什么不是"单方向"

### 反例澄清

用户可能的误解：
> "这里面的推理思路都是从单个文件提取的，这样是否不够通用？比如只能针对一个方向投资的思路？"

**实际情况**：
- Phase 5 及之前确实如此：116 个独立 pattern，99.1% 只关联 1 个 raw
- **Phase 6 已解决**：10 个通用框架 + 117 个 examples，examples 来自不同 raw、不同主题

### 复用示例

| 通用框架 | 推理骨架 | Example 1 | Example 2 | Example 3 |
|---------|---------|-----------|-----------|-----------|
| `upstream_cycle` | 验证涨价→拆解供需→对比历史→映射标的→判断持续 | MLCC 周期上行 | PCB 涨价逻辑 | 存储芯片周期 |
| `mainline_identification` | 观察资金→判断持续性→评估扩散→确认主线 | AI算力主线 | 半导体接棒 | 券商脉冲 |
| `sector_rotation` | 识别轮动信号→判断质量→评估节奏→给出优先级 | 科技→防御切换 | 成长→价值轮动 | 题材→业绩切换 |
| `earnings_analysis` | 拆解异常→还原主营→定性风险→判断估值 | 半导体业绩超预期 | 券商季报解读 | 个股暴雷识别 |

**关键**：框架的 `reasoning_chain` 描述的是**通用步骤**（如"验证涨价真实性"），不绑定具体标的；`examples` 才绑定具体标的和证据。

## 复用边界

### 什么情况下同一框架可以复用

1. **推理结构相同**：都是"涨价→供需→历史对比→标的映射"
2. **核心变量相同**：都关注价格、产能、库存、需求弹性
3. **操作模板相同**：都是"等分歧回踩，不追加速"

### 什么情况下需要新增框架

1. **推理结构完全不同**：如"事件驱动短线博弈" vs "基本面长期持有"
2. **核心变量无法归并**：如"情绪周期"（涨停家数、连板高度）vs "宏观传导"（利率、汇率、PMI）
3. **跨 3 个以上 raw 反复出现新结构**：说明 UP 有一套未覆盖的推理习惯

### 判断标准

```
新 raw 的推理链 → 与现有框架对比 →
  ├─ 步骤相似度 > 70% → 归入现有框架的 examples
  ├─ 步骤相似度 30-70% → 检查是否可扩展框架 description
  └─ 步骤相似度 < 30% → 考虑新增框架（需跨 ≥3 个 raw 验证）
```

## 实际效果

### Phase 6 实施后的数据

| 指标 | Phase 5 | Phase 6 |
|------|---------|---------|
| 框架数 | 116 个独立 | 10 个通用 |
| Examples 数 | 0（无聚合） | 117+（持续增长） |
| 跨 raw 复用率 | ~1% | ~100%（框架层面） |
| 文件大小 | 255KB | 78KB（框架）+ 线性增长 examples |

### 查询测试

```bash
cd ~/learning-investment-strategies
.venv/bin/python -c "
from qing_investment.agent.graph.nodes import _load_reasoning_patterns

# 同一框架支撑不同主题
for q in ['MLCC板块怎么看', 'PCB涨价机会', '存储芯片周期', '硅片产能']:
    state = {'query': q, 'claims': [], 'sector_context': []}
    results = _load_reasoning_patterns(state)
    print(f'{q}: {[(r[\"pattern_id\"], r.get(\"rerank_reason\",\"\")) for r in results]}')
"
```

**预期结果**：4 个不同主题的查询都应命中 `upstream_cycle`，因为它们的推理骨架相同（上游涨价周期）。

## 用户常见疑问的回应模板

### Q: "这个推理模式只能用于 MLCC 吗？"

A: 不是。`upstream_cycle` 框架的 `examples` 列表已包含 MLCC、PCB、存储、硅片等多个主题。框架的 `reasoning_chain` 是通用骨架（验证涨价→拆解供需→对比历史→映射标的→判断持续），具体标的只在 `examples` 中体现。查询"有色板块能不能买"同样会命中 `upstream_cycle`。

### Q: "如果 UP 分析了一个全新方向（如医药），现有框架能覆盖吗？"

A: 取决于推理结构：
- 如果是"涨价周期"逻辑（如原料药涨价）→ `upstream_cycle` 直接复用
- 如果是"业绩超预期"逻辑 → `earnings_analysis` 直接复用
- 如果是"政策驱动事件博弈"（如集采政策）→ 现有框架可能不覆盖，需检查是否跨 3 个以上 raw 出现，再决定是否新增框架

### Q: "examples 越来越多，会不会导致匹配噪声？"

A: 不会。匹配时只使用框架的 `name + description` 做 Embedding 召回，不使用 `examples`。`examples` 只在 Agent 执行分析时作为参考案例注入 prompt，帮助 LLM 理解框架在具体主题下的应用方式。`examples` 数量增长不影响匹配准确率。

## 维护建议

1. **定期检查 examples 分布**：运行统计脚本，确认每个框架的 examples 是否覆盖足够多的主题多样性
2. **避免 examples 过度集中于单一主题**：如 `upstream_cycle` 的 15 个 examples 不应全是 MLCC，应有 PCB、存储、硅片、有色等
3. **新增框架的门槛**：必须跨 ≥3 个 raw 反复出现，且无法归入任何现有框架
4. **框架 description 的更新**：当 examples 积累到一定数量后，检查 description 是否仍能准确概括框架的适用范围，必要时更新

## 参考实现

- 框架定义：`framework/reasoning-patterns.yaml`（10 个通用框架）
- 匹配逻辑：`src/qing_investment/agent/graph/nodes.py`（`_load_reasoning_patterns()`）
- 抽取脚本：`scripts/extract_reasoning_patterns.py`（`--single` / `--incremental`）
- 架构设计：`references/reasoning-pattern-architecture.md`
