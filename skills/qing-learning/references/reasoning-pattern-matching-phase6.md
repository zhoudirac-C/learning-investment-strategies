# 推理模式匹配算法 Phase 6：Embedding 召回 + LLM 重排序

> 关联：`references/reasoning-pattern-matching-phase5.md`（Phase 5 关键词优化）、`references/reasoning-pattern-extraction-workflow.md`（抽取脚本改造）
> 实施时间：2026-06-06

## 方案

解决 Phase 5.1 发现的 Embedding 直接替换问题：ONNX 语义召回容易把边界查询（如 MLCC/半导体业绩）误匹配到 `ai_industry_chain`。

采用**两阶段匹配**：

```
用户 query
    ↓
阶段一：ONNX Embedding 召回 Top 5
    ├─ 预计算10个框架的 embedding（name+description）
    ├─ 计算 query 与框架的余弦相似度
    └─ 取 Top 5 候选
    ↓
阶段二：LLM 重排序 Top 3
    ├─ 把5个候选的 pattern_id / name / description / similarity 发给 LLM
    ├─ LLM 根据 query 选择最相关的 1-3 个框架
    └─ 返回 [{pattern_id, reason}, ...]
    ↓
根据 LLM 结果过滤并排序，最多返回3条
```

## 为什么是两阶段

| 阶段 | 作用 | 为什么不可替代 |
|------|------|---------------|
| Embedding 召回 | 快速语义召回，不漏候选 | 同义词、近义词、描述性查询关键词匹配不到 |
| LLM 重排序 | 利用 LLM 理解框架边界 | Embedding 对边界案例（MLCC vs AI产业链）容易混淆 |

## 代码实现

### 新增/修改文件

- `src/qing_investment/agent/graph/nodes.py`
  - `_PATTERN_EMBEDDINGS_CACHE` — 框架 embedding 缓存
  - `_ensure_pattern_embeddings()` — 预计算并缓存
  - `_embed_recall_candidates()` — 阶段一
  - `_llm_rerank_patterns()` — 阶段二
  - `_load_reasoning_patterns()` — 整合两阶段 + fallback
- `src/qing_investment/agent/prompts/system/pattern_router.txt` — LLM rerank 的 system prompt

### 核心代码片段

```python
def _embed_recall_candidates(state, top_k=5):
    emb_result = _ensure_pattern_embeddings()
    patterns, pattern_embeddings = emb_result
    model = _get_embedding_model()
    query_vec = model.encode(query)
    similarities = (query_vec @ pattern_embeddings.T)[0]
    top_indices = np.argsort(similarities)[::-1][:top_k]
    return [(int(idx), float(similarities[idx])) for idx in top_indices]


def _llm_rerank_patterns(query, candidates, patterns):
    router_prompt = _load_prompt("pattern_router")
    # 构造候选文本：pattern_id + name + description + similarity
    candidate_texts = [...]
    prompt = f"{router_prompt}\n\n用户查询：{query}\n\n候选框架：\n{...}"
    content = _safe_llm_invoke(prompt)
    return json.loads(content)  # [{pattern_id, reason}, ...]
```

### Fallback

- Embedding 模型加载失败 → 回退到 Phase 5 关键词匹配
- LLM 调用失败 → 返回 Embedding Top 3

## 测试验证

```bash
cd ~/learning-investment-strategies
.venv/bin/python -c "
from qing_investment.agent.graph.nodes import _load_reasoning_patterns

for q in ['MLCC板块怎么看', '半导体业绩怎么样', '今天主线是什么', '大盘技术位置']:
    state = {'query': q, 'claims': [], 'sector_context': []}
    results = _load_reasoning_patterns(state)
    print(f'{q}: {[(r[\"pattern_id\"], r[\"match_score\"], r.get(\"rerank_reason\",\"\")) for r in results]}')
"
```

**实测结果**：

| 查询 | Embedding Top1 | LLM Rerank 结果 |
|------|---------------|-----------------|
| MLCC板块怎么看 | ai_industry_chain (0.661) | **upstream_cycle** ✅ |
| 半导体业绩怎么样 | ai_industry_chain (0.683) | **earnings_analysis** ✅ |
| 今天主线是什么 | mainline_identification | mainline_identification ✅ |
| 大盘技术位置 | technical_timing | technical_timing ✅ |

## 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| Embedding 模型 | `bge-small-zh-v1.5` (ONNX) | 512-dim，本地运行 |
| 召回数 | 5 | 给 LLM 足够候选，又不至于信息过载 |
| 返回数 | ≤3 | 控制 prompt 长度 |
| Embedding 文本 | `name + "。" + description` | 不用 themes（themes 噪声大） |
| 缓存 | `_PATTERN_EMBEDDINGS_CACHE` | 进程级，首次调用时计算 |

## Pitfalls

1. **不要用 themes 做 embedding 文本**：themes 数量多、噪声大，会把无关主题拉入相似度计算
2. **description 质量决定召回上限**：如果 description 写得不好，Embedding 召回的 Top5 会漏掉正确框架
3. **LLM prompt 必须限制只从候选中选**：否则 LLM 会编造不存在的框架
4. **ONNX 模型失败要优雅 fallback**：本地模型可能因环境问题加载失败，不能因此阻断整个 Agent
5. **相似度分数仅供参考**：最终排序由 LLM 决定，embedding similarity 只用于召回
