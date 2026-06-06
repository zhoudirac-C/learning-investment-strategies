# Phase 6 推理模式改造实施配方

> 关联：`references/reasoning-pattern-extraction-workflow.md`、`references/reasoning-pattern-matching-phase5.md`
> 用途：当需要复现或扩展 Phase 6 的两阶段匹配 + 框架归类合并时，按此配方执行。

## 目标

解决 `framework/reasoning-patterns.yaml` 中 99% 的 pattern 只关联 1 个 raw 文件的问题：
- 改造前：116 个独立 pattern，单 raw 依赖，文件持续膨胀
- 改造后：10 个通用框架 + N 个 examples，examples 自动归入对应框架

## 改造范围

| 组件 | 文件 | 改动 |
|------|------|------|
| Agent 匹配 | `src/qing_investment/agent/graph/nodes.py` | 两阶段匹配：Embedding 召回 Top5 + LLM 重排序 Top3 |
| Router Prompt | `src/qing_investment/agent/prompts/system/pattern_router.txt` | 新增 LLM rerank 的 system prompt |
| 抽取脚本 | `scripts/extract_reasoning_patterns.py` | LLM 提取时增加 `matched_framework`，合并到对应框架的 `examples` |
| YAML 数据 | `framework/reasoning-patterns.yaml` | 117 个 examples 归入 10 个框架 |

## 10 个通用框架 ID

```
upstream_cycle          # 上游涨价周期分析框架
mainline_identification # 市场主线识别与切换判断框架
sector_rotation         # 板块轮动与扩散分析框架
macro_transmission      # 宏观传导链分析框架
sentiment_cycle         # 市场情绪周期分析框架
technical_timing        # 技术择时分析框架
earnings_analysis       # 个股业绩拆解与定性分析框架
ai_industry_chain       # AI产业链传导分析框架
operation_strategy      # 操作策略与仓位管理框架
others                  # 其他独立分析框架
```

## 快速验证命令

### 1. 验证 Embedding 召回

```bash
cd ~/learning-investment-strategies
.venv/bin/python -c "
from qing_investment.agent.graph.nodes import _embed_recall_candidates
state = {'query': 'MLCC板块怎么看', 'claims': [], 'sector_context': []}
for idx, sim in _embed_recall_candidates(state, top_k=5):
    print(f'{idx}: {sim:.3f}')
"
```

### 2. 验证完整两阶段匹配

```bash
cd ~/learning-investment-strategies
.venv/bin/python -c "
from qing_investment.agent.graph.nodes import _load_reasoning_patterns
for q in ['MLCC板块怎么看', '半导体业绩怎么样', '今天主线是什么', '市场情绪如何']:
    state = {'query': q, 'claims': [], 'sector_context': []}
    results = _load_reasoning_patterns(state)
    print(f'{q}: {[(r[\"pattern_id\"], r[\"match_score\"], r.get(\"rerank_reason\",\"\")) for r in results]}')
"
```

### 3. 验证抽取脚本合并效果

```bash
cd ~/learning-investment-strategies
.venv/bin/python scripts/extract_reasoning_patterns.py --single "复盘：26-05-31：科技震荡消化拥挤，被动元件全面进入周期上行.md"
```

预期输出包含：`[merge] -> framework 'upstream_cycle' (now N examples)`

### 4. 统计当前框架状态

```bash
cd ~/learning-investment-strategies
.venv/bin/python -c "
import yaml
with open('framework/reasoning-patterns.yaml') as f:
    data = yaml.safe_load(f)
total = sum(len(p.get('examples', [])) for p in data['patterns'])
print(f'总examples: {total}')
for p in data['patterns']:
    print(f'{p[\"pattern_id\"]}: {len(p.get(\"examples\", []))} examples, {len(p.get(\"source_raw\", []))} sources')
"
```

## 新增 Prompt 模板要点

### pattern_router.txt

- 角色：推理模式路由专家
- 输入：用户查询 + 候选框架列表（含 name/description/embedding_similarity）
- 输出：JSON 数组，最多 3 个 `pattern_id`，每个带 `reason`
- 关键规则：只从候选列表中选择，不编造新框架

### EXTRACTION_PROMPT（抽取脚本）

新增字段：
- `matched_framework`: 必须从 10 个通用框架 ID 中选择
- `merge_suggestion`: 30 字以内解释归入原因
- `applicable_themes`: 3-5 个核心主题（不要罗列过多）

## 合并逻辑要点

```python
def merge_pattern_into_framework(existing_patterns, new_pattern):
    matched_fw = new_pattern.get("matched_framework", "").strip()
    for p in existing_patterns:
        if p.get("pattern_id") == matched_fw:
            example = {
                "pattern_id": new_pattern["pattern_id"],
                "name": new_pattern["name"],
                "source_raw": new_pattern["source_raw"],
                "key_themes": new_pattern["applicable_themes"],
                "reasoning_chain": new_pattern["reasoning_chain"],
                "risk_factors": new_pattern["risk_factors"],
                "confidence_indicators": new_pattern["confidence_indicators"],
                "merge_suggestion": new_pattern["merge_suggestion"],
            }
            if "examples" not in p:
                p["examples"] = []
            p["examples"].append(example)
            # 合并 themes 和 source_raw
            p["applicable_themes"] = sorted(set(p["applicable_themes"]) | set(new_pattern["applicable_themes"]))
            p["source_raw"] = sorted(set(p["source_raw"]) | set(new_pattern["source_raw"]))
            return existing_patterns
    # fallback: 找不到对应框架 → 作为独立 pattern 保留
    return existing_patterns + [new_pattern]
```

## 常见边界问题

| 问题 | 解决 |
|------|------|
| LLM 把 MLCC 误判到 `ai_industry_chain` | 两阶段匹配中 LLM rerank 会纠正；抽取 prompt 中强调"上游周期品" |
| 动态短文被错误提取 | 前 500 字分析指标检查 + `has_pattern: false` 过滤 |
| 找不到对应框架 | fallback 到独立 pattern，并打印 warn |
| 文件持续膨胀 | 检查是否大部分 examples 正确归并；独立 pattern 增长应接近 0 |

## 文档同步清单

实施 Phase 6 后必须更新：
- [ ] `src/qing_investment/agent/AGENTS.md` — 节点描述、Prompt 维护章节
- [ ] `README.md` — 推理层描述
- [ ] `skills/qing-learning/references/reasoning-pattern-matching-phase5.md` — 补充 Phase 6 实施细节
- [ ] `skills/qing-learning/references/reasoning-pattern-extraction-workflow.md` — 更新合并逻辑
