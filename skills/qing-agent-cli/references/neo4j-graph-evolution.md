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

### 错误4：claim_type 字段名不匹配（YAML vs 代码）

**场景**：迁移脚本从 YAML claim 文件读取类型时，YAML 中使用 `claim_type` 字段，但代码读取 `type` 字段。

```python
# ❌ 错误：代码只读 'type'，但 YAML 中是 'claim_type'
entity_label = get_entity_type(claim.get("type", ""), subject)
# 结果：所有 claim 的 type 为空 → 全部 fallback 为 "general"
# Neo4j 中所有 Claim 节点的 claim_type 都是 "general"

# ✅ 正确：支持双字段读取，优先 claim_type
entity_label = get_entity_type(
    claim.get("claim_type", claim.get("type", "")), 
    subject
)
```

**影响**：
- 所有 Claim 节点的 `claim_type` 属性值为 `"general"`
- `get_entity_type()` 无法正确分类为 `Stock`/`Sector`/`Macro`/`Methodology`
- 图遍历查询返回的结果缺少类型信息

**修复后验证**：
```python
from neo4j import GraphDatabase
# 检查 claim_type 分布
driver.session().run("""
    MATCH (c:Claim) 
    RETURN c.claim_type as type, count(*) as cnt 
    ORDER BY cnt DESC
""")
# 预期：sector-theme, stock-view, operation, market-cycle, risk 等多种类型
```

### 错误5：股票代码正则无法匹配 .SH/.SZ 后缀

**场景**：Claim 文件中的股票代码可能包含市场后缀（如 `000066.SZ`、`600487.SH`），但迁移脚本的正则只匹配纯数字。

```python
# ❌ 错误：只匹配 6 位纯数字
STOCK_CODE_RE = re.compile(r"\b(\d{6})\b")
# "000066.SZ" → 匹配不到 → Stock 节点为 0

# ✅ 正确：支持可选后缀
STOCK_CODE_RE = re.compile(r"\b(\d{6})(?:\.SH|\.SZ|\.sh|\.sz)?\b")
# "000066.SZ" → 提取 "000066"
```

**额外处理**：部分 claim 只写股票名称（如"中国长城"）不写代码，需通过 `positions.yaml` 中的名称→代码映射补充：

```python
# 从 positions.yaml 加载名称映射
name_to_code = {}
for pos in positions_data.get("positions", []):
    name_to_code[pos.get("name", "")] = pos.get("code", "")

# 提取时同时匹配代码和名称
codes = set(STOCK_CODE_RE.findall(text))
for name, code in name_to_code.items():
    if name in text:
        codes.add(code)
```

### 错误6：Primary entity 创建 Stock 节点时使用 name 而非 code

**场景**：迁移脚本在创建 Primary entity（subject）时，统一使用 `name` 属性，但 `Stock` 类型节点应该用 `code`。

```python
# ❌ 错误：所有实体类型都用 'name' 属性
session.run(f"MERGE (e:{entity_label} {{name: $name}})", name=subject)
# Stock 节点变成 Stock {name: '中国长城'}，无法通过 code 查询

# ✅ 正确：Stock 类型用 'code'，其他类型用 'name'
if entity_label == "Stock":
    # 尝试从 subject 提取代码，或从 name_to_code 映射查找
    stock_code = extract_stock_code(subject) or name_to_code.get(subject)
    if stock_code:
        session.run("MERGE (s:Stock {code: $code}) SET s.name = $name", 
                    code=stock_code, name=subject)
else:
    session.run(f"MERGE (e:{entity_label} {{name: $name}})", name=subject)
```

**影响**：
- `MATCH (s:Stock {code: '000066'})` 返回空
- `MATCH (s:Stock)` 返回的节点只有 `name` 属性无 `code`
- 图遍历查询完全失效

**修复后清理**：
```python
# 删除错误的 Stock 节点（无 code 属性）
session.run("MATCH (s:Stock) WHERE s.code IS NULL DELETE s")
# 重新运行迁移脚本
```

## 数据修复流程（当发现上述错误时）

若 Neo4j 数据已损坏（如所有 claim_type 为 general、Stock 节点为 0、Stock 节点属性错误），按以下流程修复：

1. **诊断**：运行 Cypher 查询确认问题范围和程度
2. **清理**：删除错误节点/关系（如 `MATCH (s:Stock) WHERE s.code IS NULL DELETE s`）
3. **修复脚本**：更新迁移脚本（claim_type 双字段、正则后缀、Stock 属性）
4. **重新迁移**：`python scripts/migrate_claims_to_neo4j.py --force-full`
5. **验证**：检查节点类型分布、Stock 节点数量、claim_type 分布
6. **同步索引**：重新运行 `index_claims_to_qdrant.py` 和 `init_mem0_memories.py`

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
