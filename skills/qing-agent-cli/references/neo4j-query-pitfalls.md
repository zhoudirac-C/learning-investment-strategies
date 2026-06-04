# Neo4j Query Pitfalls

## "property key does not exist" 警告

当 Cypher 查询访问 `Claim` 等节点上不存在的属性时，Neo4j 输出 `warn: property key does not exist`。这不阻断查询（结果正确返回），但污染日志。

### 修复方法（三层）

**第1层：查询语句** — 用 `coalesce` 兜底 + ORDER BY 使用别名

```cypher
// 错误：直接访问不存在的属性
RETURN c.source_date as source_date
ORDER BY c.source_date DESC

// 正确：coalesce 兜底，ORDER BY 用 alias
RETURN coalesce(c.source_date, '') as source_date
ORDER BY source_date DESC
```

Python 示例（`neo4j_client.py`）：
```python
query = """
MATCH (c:Claim)
WHERE c.subject CONTAINS $keyword OR c.statement CONTAINS $keyword
RETURN c.id as id, c.statement as statement,
       c.confidence as confidence, coalesce(c.source_date, '') as source_date,
       c.status as status
ORDER BY source_date DESC
LIMIT $limit
"""
```

**第2层：数据迁移** — 给已有节点补上缺失属性

```python
with driver.session() as session:
    result = session.run("""
        MATCH (c:Claim)
        WHERE c.source_date IS NULL
        SET c.source_date = ''
        RETURN count(c) as updated
    """)
```

**第3层：schema 预防** — 确保后续迁移脚本设置该属性

在 `_migrate_single_claim()` 中为 CREATE 增加 `source_date` 字段：
```python
session.run("""
    CREATE (c:Claim {
        id: $id,
        ...
        source_date: $source_date
    })
""")
```

### 排查步骤

1. 运行 `python -c "from qing_investment.agent.tools.neo4j_client import Neo4jClient; c = Neo4jClient(); print(c.get_claims_by_keyword('半导体'))"` 查看警告
2. 确认警告中提到的属性名（如 `source_date`）和节点类型（如 `Claim`）
3. 检查 `scripts/migrate_claims_to_neo4j.py` 中的 `_migrate_single_claim()` 是否设置了该属性
4. 若未设置 → 三层修复
5. 若已设置但旧节点无属性 → 执行第2层迁移
