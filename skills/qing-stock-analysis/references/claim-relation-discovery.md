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

### 测试结果

3条 dry-run 发现 1条真实矛盾：
- claim-20260414-001（中东冲突定价）CONTRADICTS claim-20260521-002-k（外盘风险对A股影响不大）
- 006-a（储能完整清单）supplements 004-e（储能核心标的）— 准确
