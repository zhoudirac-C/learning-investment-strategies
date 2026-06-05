# 推理模式抽取与集成工作流

> 关联：`references/reasoning-pattern-architecture.md`（架构设计）、`references/expert-distillation-guide.md`（整体蒸馏方案）

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
- **Pitfall**：JSON 模板中的花括号必须用 `str.replace("{content}", content)` 而非 `.format()` 替换（后者会报 `KeyError: '"has_pattern"'`）

## 3. Agent 集成架构

### 数据流

```
用户提问 "今天MLCC板块怎么看？"
    ↓
_extract_themes_from_state(state)
    ├─ query 关键词匹配 _THEME_KEYWORD_MAP
    ├─ claims subject 字段匹配
    └─ sector_context name 匹配
    → 提取主题集合：{"MLCC", "被动元件"}
    ↓
_load_reasoning_patterns(state)
    ├─ 加载 framework/reasoning-patterns.yaml
    ├─ 与 applicable_themes 取交集
    ├─ 按匹配主题数排序
    └─ 取 Top 3（控制 prompt 长度）
    ↓
market_analyst() prompt context
    → reasoning_patterns: [{pattern_id, name, reasoning_chain, risk_factors, ...}]
    ↓
LLM 按推理模式的 step 顺序执行分析
```

### 匹配机制

`_THEME_KEYWORD_MAP`（位于 `src/qing_investment/agent/graph/nodes.py`）定义了关键词→主题映射。**新增推理模式**时，如果 applicable_themes 中有新主题词，必须同步更新此映射，否则 Agent 无法匹配。

### 注入点

`market_analyst()` 的 context dict 中注入 `reasoning_patterns` 字段，与 `framework_rules` 并列。

### 行为规则

- 无主题匹配 → 返回空列表（避免无关模式干扰）
- 最多 3 条（控制 prompt 长度）
- 推理模式是辅助，实时数据优先（prompt 中明确要求）

## 4. 手动维护检查清单

- [ ] 从 raw 原文中提取 ≥3 步推理链（有"因为A→所以B→但是C"因果链）
- [ ] `pattern_id` 不与已有重复
- [ ] `applicable_themes` 在 `_THEME_KEYWORD_MAP` 中有对应关键词
- [ ] `reasoning_chain` 每步的 `UP_logic` 引用原文核心逻辑
- [ ] `risk_factors` 是原文明确提到的证伪条件

### 验证命令

```bash
# YAML 格式
python -c "import yaml; yaml.safe_load(open('framework/reasoning-patterns.yaml'))"

# 匹配逻辑
.venv/bin/python -c "
from qing_investment.agent.graph.nodes import _load_reasoning_patterns
state = {'query': 'MLCC板块分析', 'claims': [], 'sector_context': []}
print(_load_reasoning_patterns(state))
"
```

## 5. 常见陷阱

1. **混淆观点与推理**：`"UP看好MLCC"` → claims；`"UP用5步推理得出看好"` → reasoning-patterns
2. **pattern_id 重复**：脚本有去重检查，但手动添加时需注意
3. **关键词映射遗漏**：新主题未在 `_THEME_KEYWORD_MAP` 添加 → Agent 无法匹配
4. **JSON 花括号 vs .format()**：模板替换用 `str.replace()` 不用 `.format()`
5. **旧模式保护**：脚本增量发现，不覆盖手动抽取的已有模式
