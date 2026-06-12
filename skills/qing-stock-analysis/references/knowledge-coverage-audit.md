# 知识覆盖审计：三层次检查法

> 用途：当用户问"某某方法论有没有文档化/进入知识库/成为 Agent 分析方法"时，
> 用此三层次检查法给出完整答案，而非只回答其中一层。

## 三层次覆盖图

```
第一层：方法论文档（Wiki）
  ├─ knowledge/wiki/投资方法论/*.md
  ├─ framework/*.md
  └─ skills/qing-stock-analysis/references/*.md

第二层：知识库 Claims（Neo4j + Qdrant）
  ├─ claim_type: methodology
  ├─ timeframe: permanent（永久性规则）
  └─ confidence: high

第三层：Agent Prompt（运行时生效）
  ├─ src/.../prompts/system/market_analysis_framework.txt（大盘分析）
  ├─ src/.../prompts/system/market_analyst.txt（市场分析）
  ├─ src/.../prompts/system/stock_analyst.txt（个股分析——仅含使用边界声明）
  └─ src/.../prompts/system/style_writer.txt（输出风格）
```

## 检查步骤

```python
# 伪代码：三层次审计
def audit_coverage(topic: str) -> dict:
    return {
        "layer1_wiki":    search_wiki(topic),       # Qdrant knowledge collection
        "layer2_claims":  search_claims(topic),      # Qdrant claims + Neo4j
        "layer3_prompt":  grep_prompt_files(topic),  # market_analysis_framework.txt etc.
    }
```

1. **Layer 1 — Wiki/Reference 文档**：主题是否有专门的方法论文档？文档是否完整（涵盖核心规则、使用案例、边界条件）？
2. **Layer 2 — Claims**：是否有相关 claim（尤其是 `claim_type: methodology, timeframe: permanent`）？每条 claim 是否有 `evidence_quote` 可追溯原文？
3. **Layer 3 — Agent Prompt**：这些规则是否已编码到 Agent 系统 prompt 中（不仅仅是存在于知识库被检索到，而是作为硬规则写在 prompt 里强制执行）？

## 常见结论模式

| 各层状态 | 结论 |
|----------|------|
| 三层齐全 | ✅ 完全覆盖。直接引用各层来源给出结论 |
| Wiki有 + Claims有，但Prompt无 | ⚠️ 知识已入库但 Agent 执行时可能不遵守。需补充 prompt 约束 |
| Claims有，但Wiki无 | ⚠️ 有零散规则但缺乏体系化文档 |
| 三层都无 | ❌ 方法论尚未提取。需从 raw 文档提取→写 claim→建 wiki→注入 prompt |

## 历史案例：UP 大盘分析方法论审计（2026-06-12）

| 方法论 | Layer1 Wiki | Layer2 Claims | Layer3 Prompt | 结论 |
|--------|-------------|--------------|--------------|------|
| MACD 多级别结构 | ✅ 大盘分析方法论.md | ✅ 7条永久 claims | ✅ market_analysis_framework.txt | 已完整覆盖 |
| 九转序列 | ✅ 大盘分析方法论.md §1.4 | ✅ 3条永久 claims | ✅ market_analysis_framework.txt | 已完整覆盖 |
| 斐波那契时间窗口 | ✅ 大盘分析方法论.md §1.5 | ✅ 2条永久 claims | ✅ market_analysis_framework.txt | 已完整覆盖 |
| 三步共振法 | ✅ 大盘分析方法论.md §综合 | ✅ prompt-engineering-patterns.md | ✅ market_analysis_framework.txt | 已完整覆盖 |

## 注意事项

- Agent prompt 中的规则可能先于 Wiki/Claims 建立（有反例：Prompt 作为"尝鲜写入"而 Wiki/Claims 尚未补充）
- Claims 可能有多个相关但归属不同 `claim_type`（如 `methodology` 和 `technical-signal`），都需要检查
- 对于时间敏感的规则（如指数关键点位），需验证 Prompt 中的硬编码值与 strategy_pack.yaml 是否同步
