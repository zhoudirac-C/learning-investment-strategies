# Neo4j Claims 图关系使用指南

## 何时使用图遍历 vs 关键词匹配

| 查询类型 | 推荐方法 | 原因 |
|---------|---------|------|
| 个股查询（有股票代码） | **图遍历** `get_claims_with_evolution()` | 精准匹配 `:Stock {code: '000066'}`，无噪音 |
| 非个股查询（无代码） | **关键词匹配** `get_claims_by_keyword()` | 无明确股票实体，只能用关键词 |
| Claim 演化追踪 | **图关系** `SUPERSEDES`/`CONTRADICTS` | 必须遍历关系才能发现观点变化 |
| 板块关联分析 | **图遍历** `:Claim-[:ABOUT]->:Sector` | 通过 Sector 节点关联 |

## 图遍历查询示例

### 获取某股票的所有 claims（含演化关系）

```python
from qing_investment.agent.tools.neo4j_client import Neo4jClient

neo4j = Neo4jClient()
claims = neo4j.get_claims_with_evolution("000066", limit=8)

for c in claims:
    print(f"{c['id']} [{c['claim_type']}] {c['subject']}")
    if c.get('superseded_by'):
        print(f"  [已被 {', '.join(c['superseded_by'])} 取代]")
    if c.get('contradicts'):
        print(f"  [与 {', '.join(c['contradicts'])} 矛盾]")
neo4j.close()
```

### 获取与某 claim 相关的其他 claims（共享实体）

```python
related = neo4j.get_related_claims("claim-20260603-001-a", limit=10)
for r in related:
    print(f"{r['id']} via {r['entity_type']}({r['entity_name']}): {r['statement'][:100]}")
```

## Prompt 中注入演化关系标记

当 claims 包含 `superseded_by` 或 `contradicts` 时，在 prompt 中添加标记帮助 LLM 判断时效性：

```python
claim_line = f"- {c.get('id', 'N/A')} ({c.get('source_date','')})"
if c.get('claim_type'):
    claim_line += f" [{c.get('claim_type')}]"
claim_line += f": {c.get('statement', '')[:200]}"

# 添加演化关系标记
if c.get('superseded_by'):
    claim_line += f" [已被 {', '.join(c['superseded_by'][:2])} 取代]"
if c.get('contradicts'):
    claim_line += f" [与 {', '.join(c['contradicts'][:2])} 矛盾]"
```

**效果**：
```
- claim-20260519-001-b (2026-05-19) [operation]: 指数纪律线4033点...
  [已被 claim-20260519-003-a 取代]
```

LLM 看到此标记后，会优先使用最新版本（`claim-20260519-003-a`）而非旧版本。

## 常见错误

### 错误1：个股查询仍用关键词匹配

```python
# ❌ 错误：关键词匹配会返回"中国石油"等噪音
keywords = ["中国", "长城"]
for kw in keywords:
    claims = neo4j.get_claims_by_keyword(kw)  # 返回包含"中国"的所有claims

# ✅ 正确：图遍历精准匹配
claims = neo4j.get_claims_with_evolution("000066")  # 只返回关于000066的claims
```

### 错误2：忽略演化关系

```python
# ❌ 错误：不检查 claim 是否被取代
claims = neo4j.get_claims_about_stock("000066")
# 可能返回已被取代的旧观点

# ✅ 正确：使用 get_claims_with_evolution 获取演化信息
claims = neo4j.get_claims_with_evolution("000066")
# 返回包含 superseded_by / contradicts 的完整信息
```

### 错误3：Stock 节点属性错误

```python
# ❌ 错误：查询时使用 name 而非 code
MATCH (s:Stock {name: '中国长城'})<-[:ABOUT]-(c:Claim)
# 可能匹配不到（name可能为空或不同）

# ✅ 正确：使用 code 属性
MATCH (s:Stock {code: '000066'})<-[:ABOUT]-(c:Claim)
```

## 与 Qdrant 的协同

```
用户提问
  ├── 提取股票代码？
  │     ├── 是 → Neo4j 图遍历（精准）
  │     └── 否 → Qdrant 语义检索（泛化）
  └── 需要 claim 演化追踪？
        ├── 是 → Neo4j SUPERSEDES/CONTRADICTS
        └── 否 → Qdrant 向量相似度
```

**最佳实践**：
1. 先尝试提取股票代码（正则 `\d{6}`）
2. 有代码 → Neo4j 图遍历 + 演化关系
3. 无代码 → Qdrant 语义检索 + Neo4j 关键词匹配（双保险）
4. Prompt 中同时注入两种来源的 claims，标记来源
