# 知识库直接查询 — 对话 Agent 直连 Qdrant + Neo4j

> 当对话 Agent（非 LangGraph 管线）需要语义搜索 claims/wiki 或图遍历关系时使用。
> LangGraph 管线已有 `retrieve_knowledge` 节点自动处理，本文件仅服务于**对话 Agent 手动查询**。

## 环境

- **Qdrant**: 本地文件模式，`$REPO/.qdrant_data/`，无需服务端
- **Neo4j**: bolt://localhost:7687, neo4j/qingneo4j, v2026.05.0 Community
- **嵌入模型**: BGE-small-zh-v1.5 ONNX (512-dim), 单例 `OnnxEmbeddingModel`
- **项目根**: `~/learning-investment-strategies`

## Qdrant 语义搜索

```python
import sys
sys.path.insert(0, "/home/ubuntu/learning-investment-strategies/src")
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper
from qing_investment.agent.tools.embedding_utils import OnnxEmbeddingModel

qdrant = QdrantClientWrapper(local_mode=True)
model = OnnxEmbeddingModel()

query = "用户查询文本"
vec = model.encode(query).tolist()  # list[float], 512-dim

# 搜索 claims
results = qdrant.search(vec, collection="qing_claims", limit=5)
for r in results:
    print(r.payload.get("claim_id"), r.payload.get("statement")[:100])

# 搜索 knowledge/wiki
results = qdrant.search(vec, collection="qing_knowledge", limit=5)
```

**可用集合**：`qing_claims`（645 pts）、`qing_knowledge`（10880 pts）

## Neo4j 图查询

```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "qingneo4j"))

# 查询 claim 及其相邻 claims
with driver.session() as session:
    result = session.run("""
        MATCH (c:Claim {id: $claim_id})-[r:SUPERSEDES|CONTRADICTS|SUPPLEMENTS]-(other:Claim)
        RETURN c.id, type(r) as rel, other.id, other.statement
    """, claim_id="claim-20260609-005-c")
    for record in result:
        print(record)

driver.close()
```

**节点类型**: `Claim`(id, statement, claim_type, timeframe, confidence, intensity, status, source_date)
**边类型**: `SUPERSEDES`, `CONTRADICTS`, `SUPPLEMENTS`, `ABOUT`(→Stock节点)

## 常用查询模式

### 语义搜索 + 关系扩展
```python
# 1. 语义搜索找到相关 claims
vec = model.encode(query).tolist()
hits = qdrant.search(vec, collection="qing_claims", limit=5)

# 2. 对 top hit 做图遍历找关联 claims
with driver.session() as session:
    for hit in hits[:2]:
        cid = hit.payload.get("claim_id")
        result = session.run("""
            MATCH (c:Claim {id: $cid})-[r]-(other:Claim)
            WHERE type(r) IN ['SUPERSEDES', 'CONTRADICTS', 'SUPPLEMENTS']
            RETURN c.id, type(r), other.id, other.statement
        """, cid=cid)
```

### 按 claim_type 和 timeframe 过滤
```python
# Qdrant 不支持原生过滤，但可在结果中后处理
relevant = [r for r in results 
            if r.payload.get("claim_type") == "methodology" 
            and r.payload.get("timeframe") == "permanent"]
```

### 查找讨论某股票的 claims
```bash
# Neo4j Cypher: 通过 ABOUT 边找
MATCH (c:Claim)-[:ABOUT]->(s:Stock {code: '000636'})
RETURN c.id, c.statement, c.claim_type, c.confidence
```

## 陷阱

1. **Qdrant 本地模式不支持并发**：查询期间不能同时运行 Agent 索引。对话 Agent 查询是只读的，安全。
2. **ONNX 模型首次加载慢**（~2-3秒），单例模式后续调用快。
3. **QdrantClientWrapper 默认 local_mode=False**：必须显式传 `local_mode=True`，否则会尝试连接服务器。
4. **embedding 维度必须匹配**：BGE-small-zh-v1.5 = 512-dim，不能用于其他维度的集合。
5. **Neo4j 连接无需 SSL**：Community 版默认无加密。
