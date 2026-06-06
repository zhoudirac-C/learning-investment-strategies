# 推理模式抽取与集成工作流

> 关联：`references/reasoning-pattern-architecture.md`（架构设计）、`references/expert-distillation-guide.md`（整体蒸馏方案）、`references/reasoning-pattern-matching-phase6.md`（Agent 匹配算法）

## 1. 推理模式是什么

不是"UP看好MLCC"（观点/claim），而是"UP是怎么得出看好MLCC的推理步骤"。

每条推理模式包含：
- `reasoning_chain`：推理步骤序列（每步含 question、UP_logic、evidence_sources）
- `risk_factors`：证伪条件
- `confidence_indicators`：增强信心的信号
- `applicable_themes`：该模式适用的主题

## 2. 抽取脚本

`scripts/extract_reasoning_patterns.py` 从 raw 文件批量抽取推理模式。

### 用法

```bash
# 预览模式：先看有多少候选
.venv/bin/python scripts/extract_reasoning_patterns.py --dry-run --max 30

# 单篇测试
.venv/bin/python scripts/extract_reasoning_patterns.py --single "视频：26-05-23：Rubin BOM拆解.md"

# 全量提取（后台）
nohup .venv/bin/python scripts/extract_reasoning_patterns.py --max 50 > logs/reasoning_extraction.log 2>&1 &

# 增量提取（只处理新文件）
.venv/bin/python scripts/extract_reasoning_patterns.py --incremental --max 20
```

### 筛选策略

- 文件名含 `复盘`/`视频`/`早盘`/`午盘`/`周复盘`/`产业链`/`BOM` → 高分优先
- 文件大小 >500B（排除纯动态转发）
- 正文前 500 字含分析性关键词（`因为`/`所以`/`判断`/`逻辑`/`周期`/`主线`）→ 才送 LLM

### 状态管理

`.reasoning_extraction_state.json` 记录已处理文件，支持断点续跑。

### LLM 提取 Prompt 关键规则

- 只抽取 ≥3 步推理链
- 推理步骤必须来自原文，不编造
- 只有观点无推理步骤 → `has_pattern: false`
- **Phase 6 新增**：必须返回 `matched_framework` 字段（从10个通用框架ID中选择）
- **Pitfall**：JSON 模板中的花括号必须用 `str.replace("{content}", content)` 而非 `.format()` 替换（后者会报 `KeyError: '"has_pattern"'`）

## 3. Agent 集成架构

### 数据流

```
用户提问 "今天MLCC板块怎么看？"
    ↓
_load_reasoning_patterns(state)
    ├─ 阶段一：ONNX Embedding 召回 Top 5
    ├─ 阶段二：LLM 重排序 Top 3
    └─ Fallback：关键词匹配
    → 返回 [{pattern_id, name, reasoning_chain, match_score, rerank_reason}]
    ↓
market_analyst() prompt context
    → reasoning_patterns: [...]
    ↓
LLM 按推理模式的 step 顺序执行分析，每步给出判断依据
```

### 匹配机制（Phase 6：Embedding + LLM Rerank）

详见 `references/reasoning-pattern-matching-phase6.md`。

**关键参数**：
- Embedding 模型：`bge-small-zh-v1.5` (ONNX, 512-dim)
- 召回数：Top 5
- 返回数：Top 3
- Fallback：关键词匹配（Phase 5 多字段加权索引）

### 注入点

`market_analyst()` 的 context dict 中注入 `reasoning_patterns` 字段，与 `framework_rules` 并列。每个 pattern 包含 `match_score` 和 `rerank_reason`。

### 行为规则

- 无主题匹配 → 返回空列表
- 最多 3 条
- 推理模式是辅助，实时数据优先

## 4. 手动维护检查清单

- [ ] 从 raw 原文中提取 ≥3 步推理链（有"因为A→所以B→但是C"因果链）
- [ ] `pattern_id` 不与已有重复
- [ ] `applicable_themes` 准确描述该模式适用的主题
- [ ] `reasoning_chain` 每步的 `UP_logic` 引用原文核心逻辑（≤60字）
- [ ] `risk_factors` 是原文明确提到的证伪条件
- [ ] **Phase 6**：`matched_framework` 必须从10个通用框架ID中选择

### 验证命令

```bash
# YAML 格式
python -c "import yaml; yaml.safe_load(open('framework/reasoning-patterns.yaml'))"
```

```bash
# 匹配逻辑（Phase 6）
.venv/bin/python -c "
from qing_investment.agent.graph.nodes import _load_reasoning_patterns
state = {'query': 'MLCC板块分析', 'claims': [], 'sector_context': []}
print(_load_reasoning_patterns(state))
"
```

## 5. 常见陷阱

1. **混淆观点与推理**：`"UP看好MLCC"` → claims；`"UP用5步推理得出看好"` → reasoning-patterns
2. **pattern_id 重复**：脚本会自动跳过已存在的 pattern_id
3. **matched_framework 选择错误**：LLM 容易把周期品（MLCC/PCB）误判到 `ai_industry_chain`，需要 description 写得足够清晰
4. **JSON 花括号 vs .format()**：LLM prompt 中含 JSON 模板时，用 `str.replace("{content}", content)` 不用 `.format()`
5. **旧模式保护**：脚本增量发现，不覆盖手动抽取的已有模式
6. **单raw依赖**：Phase 6 已解决，抽取时直接归入通用框架的 examples

## 6. 历史调优记录

详见 `references/reasoning-pattern-matching-phase5.md` §6。

## 7. 聚合合并：从116个特定模式到10个通用框架

> 2026-06-06 session 关键发现：批量抽取的116个模式中，**99.1%只关联1个raw文件**。

详见 `references/reasoning-pattern-matching-phase5.md` §7。

## 8. Phase 6：抽取时直接归入通用框架

> 2026-06-06 session 实施：改造 `extract_reasoning_patterns.py`，让 LLM 在提取时就判断归入哪个通用框架，作为该框架的 `examples` 追加。

### 为什么这样做

| 问题 | 根因 | Phase 6 解决方式 |
|------|------|-----------------|
| 116个独立模式 | 每篇 raw 都生成一个 pattern | LLM 判断是通用框架的具体应用 |
| 99.1%单raw依赖 | 没有聚合逻辑 | 直接写入对应框架的 `examples` |
| 文件持续膨胀 | 模式数随 raw 线性增长 | 框架数固定为10，examples 增长 |
| 匹配噪声 | 太多孤立主题词 | themes 在框架层面合并去重 |

### 提取 Prompt 变化

**Phase 5 及之前**：
```json
{
  "has_pattern": true,
  "pattern_id": "...",
  "name": "...",
  "description": "...",
  "applicable_themes": [...],
  "reasoning_chain": [...]
}
```

**Phase 6**：
```json
{
  "has_pattern": true,
  "pattern_id": "mlcc_price_cycle_20260531",
  "name": "MLCC周期上行推理链",
  "matched_framework": "upstream_cycle",
  "merge_suggestion": "MLCC是典型上游周期品，涨价逻辑一致",
  "applicable_themes": ["MLCC", "被动元件", "涨价题材"],
  "reasoning_chain": [...]
}
```

### 合并逻辑

```python
def merge_pattern_into_framework(existing_patterns, new_pattern):
    matched_fw = new_pattern.get("matched_framework")
    for p in existing_patterns:
        if p.get("pattern_id") == matched_fw:
            # 构建 example
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
            p["examples"].append(example)
            # 合并 themes 和 source_raw
            p["applicable_themes"] = sorted(set(p["applicable_themes"]) | set(new_pattern["applicable_themes"]))
            p["source_raw"] = sorted(set(p["source_raw"]) | set(new_pattern["source_raw"]))
            return existing_patterns
    # 找不到对应框架 → 作为独立 pattern 保留
    return existing_patterns + [new_pattern]
```

### 效果

| 指标 | Phase 5 | Phase 6 |
|------|---------|---------|
| 通用框架数 | 10 | 10 |
| Examples 总数 | 117 | 持续增长但收敛到10个框架 |
| 单文件提取结果 | 新增独立 pattern | 追加到 framework examples |
| 文件大小 | 78KB → 稳定增长 | 线性增长但结构清晰 |

### 实测案例

处理 `复盘：26-05-31：科技震荡消化拥挤，被动元件全面进入周期上行.md`：

```
[found] pattern 'mlcc_cycle_analysis_20260531' -> framework 'upstream_cycle' (5 steps)
[merge] -> framework 'upstream_cycle' (now 15 examples)
```

### 使用建议

- 运行 `--single` 先测试单篇，确认 `matched_framework` 判断正确
- 批量提取时用 `--max 20` 小步快跑，检查合并效果
- 如果 LLM 频繁把周期品误判到 `ai_industry_chain`，检查 `upstream_cycle` 的 description 是否足够突出"涨价周期"特征
