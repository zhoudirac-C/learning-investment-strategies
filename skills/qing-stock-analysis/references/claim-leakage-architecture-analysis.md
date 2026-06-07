# Claims 泄漏路径架构分析

> 2026-06-07：评估向量库/图库个股节点在检索链路中是否会导致 LLM 过度引用 UP 历史观点的问题。

## 背景

Qing-Agent 的知识库包含 ~540 条 claims（来自 UP 视频/动态/专栏的观点提取），存储于 Neo4j（图数据库）+ Qdrant（向量数据库）。

**原始担忧**：当用户查询某只个股时，向量检索或图遍历可能返回 UP 对这只股票的历史观点，LLM 可能把这些历史观点当作当前买卖依据，而不是以实时数据为准。

**已实施的防护**：
- `claim_freshness.py`：时效衰减（≤7天=最新，8-30天=近期，31-90天=历史，>90天丢弃）
- Prompt 引用纪律："每条 claim 引用必须配对至少一条实时数据"
- `market_analyst` 节点的 `_filter_methodology_only`：大盘分析只注入方法论 claims

---

## 两条数据路径的完整数据流

### 路径A：`/chat` 端点（微信/Api 查询）

```
用户消息
  ├─ Qdrant 语义检索 qing_claims → 8条（按语义相似度）
  ├─ Qdrant 语义检索 qing_knowledge → 8条 wiki
  ├─ ⚠️ 如果有 stock_code → Neo4j 图遍历
  │   MATCH (c:Claim)-[:ABOUT]->(s:Stock {code:$code})
  │   → 返回该股票 ALL claims，不经语义筛选
  └─ 合并去重 → apply_claim_freshness
       ├─ methodology/operation → 【框架】块（不受时效限制）
       ├─ ≤7天 view → 【最新】块 "辅助参考"
       ├─ 8-30天 → 【近期】块 "参考价值递减"
       └─ 31-90天 → 【历史】块 "不得作为判断依据"
```

### 路径B：`/analyze/trigger` 端点（LangGraph Cron）

```
retrieve_knowledge 节点
  ├─ Qdrant 语义检索 qing_claims → 按 ID 从 Neo4j 拿全文
  ├─ ⚠️ 有 stock_code → Neo4j get_claims_about_stock
  ├─ _apply_claim_freshness
  └─ _detect_claim_conflicts

→ market_analyst 节点：_filter_methodology_only ✅ 过滤所有个股view
→ stock_analyst 节点： 全量 claims 传入，无过滤 ⚠️
→ synthesize 节点： _format_source_block 已移除 claim 引用 ✅
```

---

## 已消除的风险

| 风险 | 防护机制 | 效果 |
|------|---------|------|
| >90天旧claim作为当前依据 | freshness 直接丢弃 | ✅ 完全消除 |
| LLM用claim替代数据分析 | prompt 引用纪律（数据必在claim前） | ✅ 大幅降低 |
| 大盘分析被个股claim污染 | market_analyst 的 _filter_methodology_only | ✅ 完全消除 |
| 输出引用过期claim ID | _format_source_block 移除claim引用 | ✅ 完全消除 |

---

## 剩余的两条泄漏路径

### 泄漏路径1：Neo4j 图遍历 → `/chat` 个股查询（⚠️ 中风险）

**位置**：`main.py:171-175` + `nodes.py:610-612`

**机制**：当检测到 stock_code 时，Neo4j 执行 `MATCH (c:Claim)-[:ABOUT]->(s:Stock {code})` —— 这是图关系遍历，不是语义检索。**只要图中存在该股票的 claim 边，就会返回，不管内容是否相关、置信度高低。**

**问题场景**：
1. 用户问"中国长城 000066 走势如何"
2. Neo4j 返回该股票的 8 条 claims（包括 3 天前 UP 随口提的"中国长城可以关注"）
3. Freshness 过滤后，这条 3 天前 claim 标记为 **最新**
4. 进入 prompt 的【UP最新观点】块
5. LLM 无法区分"UP 认真推荐"还是"UP 随口一提"

**已有防护**：prompt 中标注"可作为辅助参考，需搭配实时数据"，但 `最新` 标签天然带权威感。

**计划修复**：方案C intensity 字段 — 区分 `high`（认真分析）/ `medium`（一般提及）/ `low`（随口一提），个股查询时过滤 `intensity=low`。

---

### 泄漏路径2：stock_analyst 全量 claims 传入（⚠️ 中低风险）

**位置**：`nodes.py:1057-1067`

**机制**：`stock_analyst` 节点的 context 字典中 `"claims": claims` 原样传入所有 claims，与 `market_analyst` 有 `_filter_methodology_only` 不同，`stock_analyst` 没有对 claims 做类型或强度过滤。

**风险较低的原因**：
- `stock_analyst` 输出是结构化的（地位、多空证据 JSON），不是最终分析文本
- 后续 `synthesize` 已移除 claim 来源引用
- 主要用于 `_extract_up_position_from_claims` 提取 UP 的个股地位标签

**建议**：方案C实施后，在 stock_analyst 中也过滤 `intensity=low` 的 claims。

---

## 数据流关键文件索引

| 文件 | 功能 | 泄漏相关 |
|------|------|---------|
| `main.py:124-196` | `/chat` 检索逻辑 | 路径1 Neo4j 图遍历 |
| `main.py:380-419` | `/chat` prompt 构建（claims 分级注入） | 路径1 最新/近期/历史分级 |
| `nodes.py:598-756` | `retrieve_knowledge` 节点 | 路径1 Neo4j + 路径2 全量传入 |
| `nodes.py:610-612` | stock_code → Neo4j 图遍历 | 路径1 核心位置 |
| `nodes.py:1039-1102` | `stock_analyst` 节点 | 路径2 全量 claims |
| `nodes.py:759-790` | `_filter_methodology_only` | 防护参考（路径1 已修复） |
| `neo4j_client.py:15-27` | `get_claims_about_stock` | 路径1 查询源头 |
| `claim_freshness.py` | 时效过滤 | 通用防护 |
| `main.py:440-511` | prompt 六步框架 + 引用纪律 | 通用防护 |

---

## 方案C（intensity 字段）影响面

详见 `docs/superpowers/plans/2026-06-07-claim-intensity-field.md`

- Schema: `claim_schema.py` 新增 `intensity` 字段（high/medium/low）
- 数据: ~540 claims 自动分类 + 人工 review
- Neo4j: 迁移加属性 + 查询加 `min_intensity` 过滤
- Qdrant: payload 加字段
- 检索: `retrieve_knowledge` 增加 intensity boost/penalty
- Prompt: 分级标签 + 引用规则
