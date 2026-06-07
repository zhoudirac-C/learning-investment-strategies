# Claim Relation Discovery

> 方案1+3实现。2026-06-07部署。

## 问题

Neo4j 图中 Claim→Claim 关系几乎全空（18条 SUPERSEDES + 7条 CONTRADICTS，占566条的4%），全靠人手写。需要自动发现。

## 方案1：图遍历（检索时，免费）

在 `retrieve_knowledge()` 和 `/chat` 中，claims 检索完成后，取 top-3 claims 做 Neo4j 图遍历：

```cypher
MATCH (c:Claim {id: $id})-[:ABOUT]->(e)<-[:ABOUT]-(related:Claim)
WHERE related.id <> c.id
RETURN related
```

合并去重后走同一套 freshness+intensity 流水线。不额外创建 Claim→Claim 边。

**代码位置**：
- `src/qing_investment/agent/graph/nodes.py` — retrieve_knowledge() 图遍历块
- `src/qing_investment/agent/main.py` — /chat 图遍历块
- `src/qing_investment/agent/tools/neo4j_client.py` — get_related_claims()

## 方案3：LLM 关系判断（写入时）

新增 claim 时，ONNX embedding 搜索 Qdrant top-3 相似 claims，LLM 判断关系：
- **supersedes**: 新 claim 取代旧 claim
- **supplements**: 新 claim 补充旧 claim（不写入 Neo4j 边）
- **contradicts**: 矛盾
- **none**: 无关

结果写入 YAML 的 `supersedes` / `contradicts` 字段，迁移时自动建边。

**脚本**: `scripts/discover_claim_relations.py`

### 用法

```bash
# 单文件
.venv/bin/python scripts/discover_claim_relations.py --file knowledge/claims/xxx.yaml --dry-run

# 单 claim
.venv/bin/python scripts/discover_claim_relations.py --claim-id "claim-20260604-006-a" --dry-run

# 全量回填（所有无关系的 claims）
.venv/bin/python scripts/discover_claim_relations.py --all-missing

# 测试模式（限制数量）
.venv/bin/python scripts/discover_claim_relations.py --all-missing --dry-run --limit 5
```

### 成本

- 新增 claim: 1次 ONNX embedding + 1次 LLM ≈ $0.001
- 全量回填（~500条）: ≈ $0.50

### 日志统计（2026-06-07 全量回填 392条）

| 关系类型 | LLM 判定次数 | Neo4j 边数 | 是否持久化 |
|----------|-------------|-----------|-----------|
| **supplements** | 753 (最多) | 0 | ❌ 不写入 |
| **none** | 650 | 0 | ❌ 不写入 |
| contradicts | 123 | 143 | ✅ |
| supersedes | 117 | 154 | ✅ |

> Neo4j 边数 > LLM 判定次数因为同一对 claim 可能被双向独立判定（A 对 B 判 supersedes，B 对 A 也判 supersedes），各自建一条有向边。

### 测试结果

3条 dry-run 发现 1条真实矛盾：
- claim-20260414-001（中东冲突定价）CONTRADICTS claim-20260521-002-k（外盘风险对A股影响不大）
- 006-a（储能完整清单）supplements 004-e（储能核心标的）— 准确

---

## 设计决策：为何 supplements/none 不写入 Neo4j

### none — 确定不写

**none = 关系的「缺失」，不是一种关系。** 在图数据库中存储「无关系」边是反模式：
- 650 条 none × 全量运行 ≈ 数千条无意义边，查询 `MATCH (:Claim)-[:NONE]->(:Claim)` 毫无业务价值
- 缺失 SUPERSEDES/CONTRADICTS 边本身就是「无关系」信号，不需要显式存储

### supplements — 有意不写，但可讨论

**当前设计理由：**

| 维度 | SUPERSEDES/CONTRADICTS | SUPPLEMENTS |
|------|----------------------|-------------|
| 改变 claim 有效性 | ✅ 取代=旧 claim 失效；矛盾=需二选一 | ❌ 只是信息增量，不改变任何 claim 的判断 |
| 对 Agent 决策影响 | 高——「这个观点已被取代/被反驳」直接影响操作建议 | 低——「还有更多细节可参考」不改变方向判断 |
| 检索链覆盖情况 | 唯一发现取代/矛盾的机制，无替代路径 | Qdrant 语义相似 + `get_related_claims()` entity 图遍历已能发现相关 claims |

**代码实现层面**：`discover_claim_relations.py:177-182` 只收集 supersedes 和 contradicts，supplements 虽写入 `pairs` 数组（用于日志输出）但不进入 `results["supersedes"]` / `results["contradicts"]`，因此不会被写入 YAML，也不会被 Neo4j 迁移脚本建边。

**Agent 消费端**：`get_claims_with_evolution()`（`/chat` 个股查询调用）返回 `supersedes` / `superseded_by` / `contradicts` 三个数组注入 prompt。如果将来写入 SUPPLEMENTS 边，只需在此方法加一条 `OPTIONAL MATCH` + `collect()`。

**是否值得加？** 753 条 supplements 边会让 `collect(DISTINCT supp.id)` 返回的数组很长，prompt 膨胀明显，但决策价值低。当前的设计判断是「不值得」，因此不写入。

### 如果要加 — 改动清单（~10行代码）

1. `discover_claim_relations.py` — `process_claim()` 加 `elif relation == "supplements"` 分支（类比第 177-182 行）
2. Neo4j 迁移脚本 — 加 `SUPPLEMENTS` 关系类型
3. `neo4j_client.py` — `get_claims_with_evolution()` 加 `OPTIONAL MATCH (c)-[:SUPPLEMENTS]->(supp:Claim)` + `collect(DISTINCT supp.id) as supplements`

---

## 陷阱与已知问题

### 陷阱1：--all-missing 重复判断 supplements/none

**症状**：每次 `--all-missing` 会把 90%+ 的 claims 重新跑一遍 LLM，即使结果和上次一样。

**原因**：跳过条件只检查 YAML 中是否有 `supersedes` 或 `contradicts` 字段。但 supplements/none 的判定结果不写入 YAML（见设计决策），因此下次判为"缺失关系 → 需处理"。

**量化**：578 条 claim，仅 ~34 写出了关系，剩下 **544 条下次会全量重判**。每次 544×3 ≈ 1632 次 LLM 调用空转（约 $1.6/次）。

**修复方案**：在 YAML 中加 `last_discovered` 标记，`--all-missing` 改为检查此标记跳过：
- `discover_claim_relations.py:302-306` — 跳过条件改为 `if c.get("last_discovered"): continue`
- `write_results_to_yaml()` — 无论结果如何，写入 `last_discovered: YYYY-MM-DDTHH:MM:SS`

### 陷阱2：检索链路不一致 — LangGraph 不消费 CONTRADICTS 边

**症状**：`reviewer.txt` prompt 第 6 行要求"检查是否与UP的历史立场矛盾？（检查 contradicts 关系）"，但代码未提供数据。

**原因**：两条检索路径使用了不同的 Neo4j 方法：

| 路径 | 文件 | 方法 | 含演化关系？ |
|------|------|------|-------------|
| /chat | main.py:177 | get_claims_with_evolution() | 含 supersedes/contradicts 数组 |
| /analyze/trigger | nodes.py:637 | get_claims_about_stock() | 裸 claim，无边信息 |

`_format_claim_line()`（在 main.py 中）会渲染 `[已被 xxx 取代]`、`[与 xxx 矛盾]` 标签，但 LangGraph 链路（/analyze/trigger）拿到的 claims 没有这些字段。

此外，`_detect_claim_conflicts()`（nodes.py:542-595）用关键词启发式匹配多头/空头词表来检测矛盾，不查 Neo4j 的 CONTRADICTS 边。Neo4j 里 143 条 contradicts 关系未被图分析链路消费。

**修复**：nodes.py:637 改用 `get_claims_with_evolution()`。1 行改动。

### 陷阱3：get_claim_evolution() 的演化信息被浪费

**查询结构**：多个 OPTIONAL MATCH 产生笛卡尔积（如 2 supersedes + 1 contradicts → 3 行）。但调用方（nodes.py:658、main.py:218）只取了 `first.get("c", {})`，丢弃了 old/opp/new。查都查了，但白查了。

**修复**：统一改用 `get_claims_with_evolution()` 的 `collect(DISTINCT ...)` 模式。
