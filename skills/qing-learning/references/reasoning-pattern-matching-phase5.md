# 推理模式匹配算法 Phase 5 优化记录

> 关联：`references/reasoning-pattern-extraction-workflow.md`（完整工作流）、`references/reasoning-pattern-architecture.md`（架构设计）
> 触发场景：聚合到10个通用框架后，原匹配算法（仅索引 `applicable_themes`）产生大量噪声匹配。

## 问题诊断

聚合后10个通用框架的 `applicable_themes` 每个有40-90个主题词，原算法（Phase 4）出现以下问题：

| 问题 | 表现 | 根因 |
|------|------|------|
| 滑动窗口噪声 | "MLCC"被拆成 ML/LC/CC/MLC/LCC | 2-4字滑动窗口无优先级 |
| 多框架命中 | 任何短关键词命中多个框架 | 10个框架theme集合高度重叠 |
| 阈值过低 | MIN_MATCH_SCORE=0.4 太容易触发 | 聚合后IDF权重变高，单关键词即可过阈值 |
| 字段单一 | 只索引 themes，未利用 name/description | 丢失语义信息 |
| 返回过多 | Top 5 引入无关模式 | prompt 变长，干扰LLM |

## 优化方案（已实施）

### 1. 多字段倒排索引

索引4个字段，按优先级加权：

| 字段 | 权重 | 说明 |
|------|------|------|
| `applicable_themes`（精确匹配） | 3.0 | 完整主题词命中，最高权重 |
| `applicable_themes`（2字片段） | 1.0 | 长主题词拆分，降级权重 |
| `pattern_id` + `name` | 2.5 | 框架标识文本 |
| `description` | 1.5 | 描述文本 |
| `reasoning_chain.step.name` | 1.0 | 推理步骤名 |

### 2. 精确匹配优先

`_extract_themes_from_state()` 改进：

```python
# 1. 先匹配完整主题词（从 patterns 预加载所有 themes）
for theme in all_themes:
    if theme in query:
        keywords.add(theme)

# 2. 再用2-4字滑动窗口补充
for size in (2, 3, 4):
    ...
```

### 3. 参数调整

| 参数 | 原值 | 新值 | 理由 |
|------|------|------|------|
| `MIN_MATCH_SCORE` | 0.4 | **1.5** | 聚合后需要更高阈值过滤噪声 |
| 返回数量 | Top 5 | **Top 3** | 降低 prompt 长度 |
| 索引缓存 | 无 | `_PATTERN_INDEX_CACHE` | 避免每次重建 |

### 4. 匹配信息透明化

返回字段从 `match_keywords` 细分为：
- `match_themes` — 精确命中的主题词
- `match_name_keywords` — 命中 name/description 的关键词
- `match_score` — 加权总分

## 测试验证

```python
# 验证命令
.venv/bin/python -c "
from qing_investment.agent.graph.nodes import _load_reasoning_patterns

for q in ['MLCC板块怎么看', 'AI产业链机会', '市场情绪如何', '大盘技术位置']:
    state = {'query': q, 'claims': [], 'sector_context': []}
    results = _load_reasoning_patterns(state)
    print(f'{q}: {[(r[\"pattern_id\"], r[\"match_score\"]) for r in results]}')
"
```

**预期结果**：
- "MLCC板块怎么看" → upstream_cycle (高分), mainline_identification (中分)
- "AI产业链机会" → ai_industry_chain (高分), mainline_identification (中分)
- "市场情绪如何" → sentiment_cycle (高分)
- "大盘技术位置" → technical_timing (高分)
- 无主题闲聊 → 空列表

## Phase 5.1: ONNX Embedding 语义匹配评估

> 2026-06-06 session：评估本地 ONNX `bge-small-zh-v1.5` 模型替代关键词匹配的可行性。

### 环境状态

- `onnxruntime` 1.25.1 ✅
- `models/onnx/model_quantized.onnx`（bge-small-zh-v1.5, 512-dim）✅
- `embedding_utils.py` 已封装 `OnnxEmbeddingModel` ✅
- 推理速度：CPU 单条约 50-100ms ✅

### 评估结论

**ONNX 本身完全可用，但直接替换关键词匹配效果反而下降。**

| 查询 | 关键词匹配 Top1 | Embedding Top1（旧description） | Embedding Top1（新description） |
|------|----------------|-------------------------------|-------------------------------|
| MLCC板块怎么看 | upstream_cycle ✅ | others ❌ | ai_industry_chain ❌ |
| 半导体业绩怎么样 | earnings_analysis ✅ | ai_industry_chain ❌ | ai_industry_chain ❌ |
| 今天主线是什么 | mainline_identification ✅ | mainline_identification ✅ | mainline_identification ✅ |
| 市场情绪如何 | sentiment_cycle ✅ | sentiment_cycle ✅ | sentiment_cycle ✅ |
| 大盘技术位置 | technical_timing ✅ | technical_timing ✅ | technical_timing ✅ |
| 涨价周期判断 | upstream_cycle ✅ | upstream_cycle ✅ | upstream_cycle ✅ (0.838) |

### 根因分析

1. **bge-small 对短查询边界理解有限**：当查询同时命中多个框架关键词时容易混淆
2. **description 质量决定匹配质量**：旧description 20-50字、无触发场景 → 匹配噪声大
3. **"others"框架是最大噪声源**：description "暂无法归入上述类别" 太泛，任何查询都容易匹配到
4. **"AI产业链"框架成黑洞**：包含太多具体技术词（算力/芯片/PCB），把半导体/芯片/PCB相关查询都吸过去

### Description 重写策略（已实施）

将10个框架的description从20-50字扩展到100-200字，每个description包含：
1. **触发场景**："当用户询问...时使用"
2. **典型查询示例**：4-6个常见问法
3. **核心关注点**：这个框架解决什么问题
4. **推理链概括**：框架的4-5个步骤

重写后效果：10/16查询准确命中，但边界案例（MLCC/半导体业绩/芯片股）仍有问题。

### 最终建议：两阶段匹配（Embedding + LLM Rerank）

**不要直接用Embedding替换关键词匹配**。最佳方案：

1. **Embedding 召回 Top 5**：ONNX 快速召回语义相关候选（避免漏掉同义词/近义词）
2. **LLM 重排序 Top 3**：把5个候选的 name+description 发给 LLM，让LLM根据query选出最相关的1-3个

这样 LLM 看到 "MLCC板块怎么看" 的候选里有 upstream_cycle（涨价周期）和 ai_industry_chain（AI产业链），会正确选择 upstream_cycle。

**实现路径**：
- Phase 5.1（当前）：关键词匹配（已优化）
- Phase 5.2（下一步）：Embedding 召回 + LLM rerank
- Phase 5.3（远期）：纯 Embedding（等 description 质量进一步提升或换更大模型）

## Phase 6：两阶段匹配实施（2026-06-06）

### 实现

已在 `src/qing_investment/agent/graph/nodes.py` 中实现：

1. **`_embed_recall_candidates(state, top_k=5)`**：ONNX embedding 计算 query 与 10 个框架的语义相似度，取 Top 5
2. **`_llm_rerank_patterns(query, candidates, patterns)`**：加载 `pattern_router.txt` prompt，LLM 返回最相关的 1-3 个 `pattern_id`
3. **`_load_reasoning_patterns(state)`**：整合两阶段逻辑，embedding/LLM 失败时 fallback 到关键词匹配

### 新增文件

- `src/qing_investment/agent/prompts/system/pattern_router.txt` — LLM rerank 的 system prompt

### 测试结果

| 查询 | Embedding Top1 | LLM Rerank 结果 | 是否正确 |
|------|---------------|-----------------|---------|
| MLCC板块怎么看 | ai_industry_chain (0.661) | **upstream_cycle** ✅ | ✅ |
| 半导体业绩怎么样 | ai_industry_chain (0.683) | **earnings_analysis** ✅ | ✅ |
| 今天主线是什么 | mainline_identification | mainline_identification | ✅ |
| 市场情绪如何 | sentiment_cycle | sentiment_cycle | ✅ |

### Fallback 验证

embedding 模型加载失败时，自动回退到 Phase 5 关键词匹配，仍能正确匹配。

### 代码位置

- 核心函数：`src/qing_investment/agent/graph/nodes.py`
  - `_embed_recall_candidates()` — Embedding 召回
  - `_llm_rerank_patterns()` — LLM 重排序
  - `_load_reasoning_patterns()` — 主匹配逻辑（Phase 6 整合版）
- Prompt：`src/qing_investment/agent/prompts/system/pattern_router.txt`
- 文档：`src/qing_investment/agent/AGENTS.md` — Prompt 维护章节
