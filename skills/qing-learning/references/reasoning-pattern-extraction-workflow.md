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

### 匹配机制（多字段加权倒排索引，Phase 5 优化）

匹配不再使用固定 `_THEME_KEYWORD_MAP`，改用动态多字段倒排索引方法：

1. **关键词提取**：从 query 用**完整主题词优先**+2-4字滑动窗口补充，过滤纯虚词（`怎么`/`是否`/`什么`）
2. **多字段索引构建**：索引4个字段：
   - `applicable_themes` → 权重 3.0（精确匹配，最高）
   - `pattern_id` + `name` → 权重 2.5
   - `description` → 权重 1.5
   - `reasoning_chain.step.name` → 权重 1.0
3. **IDF 加权评分**：关键词权重 = `1/log(命中pattern数 + 2)`，罕见关键词权重高，泛化词权重低
4. **最低分过滤**：score ≥ 1.5（Phase 5：从 0.4 提高，减少聚合后10个框架的噪声匹配）
5. **上限**：Top 3 条（Phase 5：从 5 减少到 3，降低 prompt 长度）

**关键参数**（Phase 5 更新）：
- `MIN_MATCH_SCORE = 1.5`（位于 `_load_reasoning_patterns()`）
- 多字段权重：`theme=3.0`, `name=2.5`, `description=1.5`, `step_name=1.0`
- 停用词列表：`_extract_themes_from_state()` 和 `_extract_keywords_from_text()` 中的 `_STOP_WORDS`
- 缓存：`_PATTERNS_CACHE` + `_PATTERN_INDEX_CACHE` 进程级缓存

### 注入点

`market_analyst()` 的 context dict 中注入 `reasoning_patterns` 字段，与 `framework_rules` 并列。每个 pattern 包含 `match_themes` 和 `match_name_keywords`，方便 LLM 理解匹配来源。

### 行为规则

- 无主题匹配 → 返回空列表（避免无关模式干扰）
- 最多 3 条（Phase 5：控制 prompt 长度）
- score < 1.5 过滤（Phase 5：聚合后10个框架需要更高阈值）
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
```

```bash
# 匹配逻辑（Phase 5 优化版）
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

> 来源：2026-06-05 session，从 35→116 条模式的匹配噪声和召回问题中迭代得出。

### 抽取规模

| 阶段 | 处理文件 | 新增模式 | 累计模式 | 备注 |
|------|---------|---------|---------|------|
| 手动 | 2（MLCC 案例） | 4 | 4 | 模板验证 |
| Phase 1 | 50（高分候选） | 31 | 35 | `--max 50`，首次批量 |
| Phase 2 | 150（增量） | 81 | 116 | `--incremental --max 150`，覆盖剩余高分文件 |
| **Phase 3: 聚合** | — | **10** | **10** | 将116个单raw模式聚合成10个通用框架 |

**问题演进**：

| 迭代 | 方案 | 问题 |
|------|------|------|
| v1 | 固定 `_THEME_KEYWORD_MAP`（8个主题） | 新增模式 30+ 条后，映射表手工维护不现实 |
| v2 | 动态倒排索引 + 简单计数 | "分析"→11 patterns，"板块"→碰任何查询都命中Top5 |
| v3 | 动态倒排索引 + 停用词过滤（大量投资术语） | 停用词过猛，AIDC/算力/能源等合法查询也被过滤 |
| v4 | 动态倒排索引 + IDF 加权 + 仅滤虚词 | MIN_MATCH_SCORE=0.8 对\"存储\"(6 patterns, IDF≈0.48)等中等稀有词过于严格 |
| v5 | v4 + MIN_MATCH_SCORE=0.4 | 存储芯片/地缘冲突/第二只脚等之前漏掉的查询全部恢复 |
| **v6: 聚合** | **10个通用框架 + examples子文档** | **解决99.1%单raw依赖问题，模式从特定场景变为可复用框架** |

**v4 关键参数**：
- 停用词：仅 18 个纯虚词（`怎么`/`是否`/`什么`/`今天`/`当前`/`最近`/`现在`/`这种`/`应该`/`可以`/`需要`/`关注`/`注意`/`一个`/`还有`/`有没有`/`哪些`/`处于`/`如何`/`怎么样`）
- `MIN_MATCH_SCORE = 0.4`（从 0.8 下调，见 §6 v5）
- IDF 公式：`1 / log(hit_count + 2)`（+2 防除零）
- "MLCC"→2 patterns: IDF≈0.72，"分析"→11: IDF≈0.39

**验证结果**（v4, 35 条模式）：

```
AIDC/算力  → 5条（基建资本循环 3.02）
AI全产业链 → 5条（全产业链共振 2.14）
MLCC       → 2条（涨价周期定性 1.34）
能源冲突   → 1条（双锚点驱动 1.44）
风格切换   → 2条（能源冲击重估 1.82）
机器人     → 3条（全产业链共振 1.82）
无主题闲聊 → 0条
```

**验证结果**（v5, 116 条模式，MIN_MATCH_SCORE=0.4）：

```
AIDC基建   → 5条（基建资本循环 2.66）
AI全产业链 → 5条（全产业链共振 1.62）
大宗商品   → 4条（康波周期切换 1.67）new!
存储芯片   → 5条（轮动质量评估 0.72）v5修复
地缘冲突   → 5条（BOM价值量链 0.72）  v5修复
第二只脚   → 3条（恐慌底确认 0.62）   v5修复
MLCC       → 5条（MLCC周期定性 0.89）
AI算力     → 5条（全产业链共振 2.24）
无主题     → 0条
```

## 7. 聚合合并：从116个特定模式到10个通用框架

> 2026-06-06 session 关键发现：批量抽取的116个模式中，**99.1%只关联1个raw文件**，导致每个模式都是"特定场景推理"而非"通用推理框架"。

### 问题诊断

| 问题 | 数据 |
|------|------|
| 单raw依赖 | 115/116 个模式只关联1个raw |
| 主题孤岛 | 82.2%的主题只出现1次 |
| 文件膨胀 | 255.7KB，持续增长无收敛 |
| 匹配噪声 | 303个主题中大量孤立词 |

### 根因

抽取脚本的筛选逻辑把"有推理链"等同于"应该抽取为模式"，但没有判断：
- 这条推理链**是否已经存在**于模式库中？
- 这条推理链的**抽象级别**是否值得独立成模式？
- 这条推理链是否只是某个通用模式的**具体应用**？

### 聚合策略

将116个模式按**推理结构相似性**聚类为10个通用框架：

| 通用框架 | 合并原模式数 | 核心推理链 |
|----------|------------|-----------|
| `upstream_cycle` | 14 | 确认涨价→分析供需→对比历史→受益映射→判断持续性 |
| `mainline_identification` | 34 | 确认市场阶段→识别候选主线→验证强度→排除假切换→制定策略 |
| `sector_rotation` | 15 | 判断触发因素→评估轮动质量→定位受益环节→判断持续性 |
| `macro_transmission` | 16 | 定性事件→分析传导路径→定位A股影响→制定对冲策略 |
| `sentiment_cycle` | 11 | 定位情绪阶段→识别拐点→筛选修复方向→制定仓位策略 |
| `technical_timing` | 6 | 判断大盘位置→分析技术形态→确认买卖信号→设置风控 |
| `earnings_analysis` | 6 | 拆解异常项→还原主营→定性风险→判断估值 |
| `ai_industry_chain` | 6 | 识别突破→拆解影响→验证需求→映射标的 |
| `operation_strategy` | 5 | 评估环境→确定仓位→选择工具→执行风控 |
| `others` | 3 | 识别特殊信号→分析影响→制定应对方案 |

### 通用框架 YAML 结构

每个通用框架包含：
- `pattern_id` / `name` / `description` — 通用描述
- `applicable_themes` — 合并所有原模式的themes（去重）
- `reasoning_chain` — **通用化**的推理步骤（抽象级别，不含具体标的/日期）
- `risk_factors` / `confidence_indicators` — 通用条件
- `examples` — 保留原模式作为**具体案例**（含原pattern_id、name、source_raw）
- `merged_from` — 记录合并来源（可追溯）

### 聚合效果

| 指标 | 原文件 | 聚合后 |
|------|--------|--------|
| 模式数 | 116 | **10** |
| 文件大小 | 255.7KB | **78.6KB** |
| 主题覆盖 | 303 | **303**（100%保留） |
| 单raw依赖 | 99.1% | **0%** |

### 聚合操作脚本

```python
# 核心逻辑：按关键词聚类 → 提取通用reasoning_chain → 保留examples
clusters = {
    'upstream_cycle': {
        'name': '上游涨价周期分析框架',
        'ids': ['upstream_price_cycle_qualify', 'upstream_beneficiary_screening', ...],
        'generic_chain': [...]  # 5步通用链
    },
    # ... 其他9个框架
}
```

详见 `references/reasoning-pattern-aggregation.md`（聚合过程完整记录）。

### 后续匹配算法建议

聚合后10个框架的`applicable_themes`更大，简单关键词匹配会产生噪声。建议：
1. **语义路由**：用LLM判断查询属于哪个框架（而非关键词硬匹配）
2. **两阶段匹配**：先框架级匹配（10选1-2），再example级细化
3. **框架优先级**：`mainline_identification`（34个原模式）主题最泛，匹配时需降权或最后考虑
