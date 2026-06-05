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
    ├─ query 2-4字滑动窗口 → 候选关键词（过滤虚词）
    ├─ claims subject 字段 → 候选关键词
    └─ sector_context name → 候选关键词
    → 关键词集合：{"mlcc", "被动", "元件", "涨价", "逻辑", ...}
    ↓
_load_reasoning_patterns(state)
    ├─ 加载 framework/reasoning-patterns.yaml（缓存）
    ├─ 构建倒排索引：applicable_themes → 关键词→[pattern_idx]
    ├─ IDF 加权评分：罕见词权重大，泛化词权重小
    ├─ MIN_MATCH_SCORE=0.8 过滤噪声
    └─ 取 Top 5
    ↓
market_analyst() prompt context
    → reasoning_patterns: [{pattern_id, name, reasoning_chain, risk_factors, match_score, ...}]
    ↓
LLM 按推理模式的 step 顺序执行分析，每步给出判断依据
```

### 匹配机制（倒排索引 + IDF 加权）

匹配不再使用固定 `_THEME_KEYWORD_MAP`，改用动态倒排索引方法：

1. **关键词提取**：从 query 用 2-4 字滑动窗口提取候选关键词，过滤纯虚词（`怎么`/`是否`/`什么`）
2. **倒排索引构建**：将所有 pattern 的 `applicable_themes` 拆为 2-4 字片段，建立 关键词→[pattern_idx] 索引
3. **IDF 加权评分**：关键词权重 = `1/log(命中pattern数 + 2)`，罕见关键词（MLCC→2 patterns）权重高，"分析"→11 patterns 权重低
4. **最低分过滤**：score ≥ 0.8（约等于 ≥2 个有区分力的关键词命中）
5. **上限**：Top 5 条（按加权分降序）

**关键参数**：
- `MIN_MATCH_SCORE = 0.8`（位于 `_load_reasoning_patterns()`）
- 停用词列表（`_extract_themes_from_state()` 中的 `_STOP_WORDS`）：只过滤纯虚词，保留所有投资主题术语
- 缓存：`_PATTERNS_CACHE` 进程级缓存，首次调用时加载 `reasoning-patterns.yaml`

### 注入点

`market_analyst()` 的 context dict 中注入 `reasoning_patterns` 字段，与 `framework_rules` 并列。

### 行为规则

- 无主题匹配 → 返回空列表（避免无关模式干扰）
- 最多 5 条（控制 prompt 长度，IDF 加权后在 `_load_reasoning_patterns` 中截断）
- score < 0.8 过滤（排除仅靠泛化词命中的噪声匹配）
- 推理模式是辅助，实时数据优先（`market_analyst.txt` 中明确要求）

## 4. 手动维护检查清单

- [ ] 从 raw 原文中提取 ≥3 步推理链（有"因为A→所以B→但是C"因果链）
- [ ] `pattern_id` 不与已有重复
- [ ] `applicable_themes` 准确描述该模式适用的主题（倒排索引会自动匹配，无需维护关键词映射表）
- [ ] `reasoning_chain` 每步的 `UP_logic` 引用原文核心逻辑（≤50字）
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
2. **pattern_id 重复**：脚本会自动跳过已存在的 pattern_id
3. **过度泛化的 applicable_themes**：主题词太泛（如仅"分析""判断"）会导致 IDF 权重很低但不致命；真正的问题是 applicable_themes 与 pattern 实际内容不匹配
4. **JSON 花括号 vs .format()**：LLM prompt 中含 JSON 模板时，用 `str.replace("{content}", content)` 不用 `.format()`（后者报 `KeyError`）
5. **旧模式保护**：脚本增量发现，不覆盖手动抽取的已有模式
6. **窗口大小不一致**：关键词提取和倒排索引构建必须用相同的窗口大小（2-4字），否则匹配率为零

## 6. IDF 加权调优记录

> 来源：2026-06-05 session，从 35 条模式的匹配噪声问题中迭代得出。

**问题演进**：

| 迭代 | 方案 | 问题 |
|------|------|------|
| v1 | 固定 `_THEME_KEYWORD_MAP`（8个主题） | 新增模式 30+ 条后，映射表手工维护不现实 |
| v2 | 动态倒排索引 + 简单计数 | "分析"→11 patterns，"板块"→碰任何查询都命中Top5 |
| v3 | 动态倒排索引 + 停用词过滤（大量投资术语） | 停用词过猛，AIDC/算力/能源等合法查询也被过滤 |
| v4 | 动态倒排索引 + IDF 加权 + 仅滤虚词 | ✓ 最终方案 |

**v4 关键参数**：
- 停用词：仅 18 个纯虚词（`怎么`/`是否`/`什么`/`今天`/`当前`/`最近`/`现在`/`这种`/`应该`/`可以`/`需要`/`关注`/`注意`/`一个`/`还有`/`有没有`/`哪些`/`处于`/`如何`/`怎么样`）
- `MIN_MATCH_SCORE = 0.8`
- IDF 公式：`1 / log(hit_count + 2)`（+2 防除零）
- "MLCC"→2 patterns: IDF≈0.72，"分析"→11: IDF≈0.39

**验证结果**（v4）：

```
AIDC/算力  → 5条（基建资本循环 3.02）
AI全产业链 → 5条（全产业链共振 2.14）
MLCC       → 2条（涨价周期定性 1.34）    ← 从5条聚焦到2条
能源冲突   → 1条（双锚点驱动 1.44）      ← 最精准
风格切换   → 2条（能源冲击重估 1.82）
机器人     → 3条（全产业链共振 1.82）
无主题闲聊 → 0条                           ← 正确过滤
```
