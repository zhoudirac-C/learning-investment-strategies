# Neo4j 图数据库诊断与修复手册

## 背景

2026-06-06 用户质疑 Qing-Agent 的推理框架是否只能针对单一方向投资思路。深入排查后发现，Neo4j 图数据库存在严重数据质量问题，导致 claims 的关系图谱价值未发挥。

## 当前状态快照（2026-06-06 修复后）

| 指标 | 修复前 | 修复后 | 健康标准 |
|------|--------|--------|---------|
| Claims 节点 | 540 | 540 | — |
| 关系总数 | 1,105 | ~1,500 | — |
| SUPERSEDES 关系 | 18 | 18 | 应有数百条 |
| CONTRADICTS 关系 | 7 | 7 | 应有数十条 |
| Stock 节点 | **0** | **38** | ✅ 已修复 |
| Macro 节点 | **0** | **102** | ✅ 已修复 |
| Methodology 节点 | **0** | **118** | ✅ 已修复 |
| Sector 节点 | 28 | 167 | ✅ 已修复 |
| Theme 节点 | 465 | 465 | — |
| claim_type 分布 | 全部 `general` | 9种类型 | ✅ 已修复 |

## 根因分析（已修复）

### 根因1：字段映射错误（claim_type vs type）✅ FIXED

**位置**：`scripts/migrate_claims_to_neo4j.py` 第 243 行

**错误代码**：
```python
"claim_type": claim.get("type", "general"),  # YAML里是 claim_type 字段
```

**问题**：Claims YAML 中使用的是 `claim_type` 字段（如 `claim_type: stock-view`），但代码读取的是 `type` 字段。由于 `type` 不存在，全部 fallback 到 `general`。

**修复**：
```python
"claim_type": claim.get("claim_type", claim.get("type", "general")),
```

### 根因2：股票代码提取正则缺陷 ✅ FIXED

**位置**：`scripts/migrate_claims_to_neo4j.py` 第 41 行

**错误代码**：
```python
STOCK_CODE_RE = re.compile(r"\b(\d{6})\b")
```

**问题**：
1. Claims 中的股票代码可能带 `.SH`/`.SZ` 后缀（如 `000066.SZ`），正则无法匹配
2. 中文文本中股票代码前后可能没有单词边界（如"中国长城000066走势"）
3. 部分 claims 只提股票名称不提代码

**修复**：
```python
# 支持 .SH/.SZ 后缀
STOCK_CODE_RE = re.compile(r"\b(\d{6})(?:\.SH|\.SZ|\.sh|\.sz)?\b")

# 同时从 positions.yaml 加载股票名称映射
def _load_stock_name_mapping() -> dict[str, str]:
    mapping = {}
    try:
        positions_path = Path("config/stock_monitor/positions.yaml")
        if positions_path.exists():
            import yaml
            data = yaml.safe_load(positions_path.read_text())
            for account in data.get("accounts", []):
                for pos in account.get("positions", []):
                    name = pos.get("name", "")
                    code = pos.get("code", "").replace(".SZ", "").replace(".SH", "")
                    if name and code:
                        mapping[name] = code
    except Exception:
        pass
    return mapping
```

### 根因3：Stock 节点属性错误 ✅ FIXED

**位置**：`scripts/migrate_claims_to_neo4j.py` 第 309-320 行

**问题**：Primary entity 创建时，当 `entity_label == "Stock"`，代码仍然使用 `MERGE (e:Stock {name: $name})`，导致 Stock 节点只有 `name` 属性而没有 `code` 属性。

**修复**：
```python
if entity_label == "Stock":
    stock_codes = extract_stock_codes(subject)
    if stock_codes:
        code = list(stock_codes)[0]
        session.run("""
            MERGE (e:Stock {code: $code})
            SET e.name = $name
            WITH e
            MATCH (c:Claim {id: $cid})
            MERGE (c)-[:ABOUT {relation_type: 'primary'}]->(e)
        """, {"code": code, "name": subject, "cid": cid})
```

### 根因4：/chat 端点未使用图遍历 ✅ FIXED

**位置**：`src/qing_investment/agent/main.py` 第 149-168 行

**问题**：
- `/chat` 只用了 `get_claims_by_keyword()`（关键词匹配）
- 没有用 `get_claims_about_stock()`（图遍历）
- 没有用 `get_claim_evolution()`（关系追踪）

**修复后逻辑**：
```python
if fetched_stock_code:
    # 个股查询：使用图遍历获取相关 claims（含演化关系）
    stock_claims = neo4j.get_claims_with_evolution(fetched_stock_code, limit=8)
    for c in stock_claims:
        c["source"] = "neo4j_graph"
        claims.append(c)
else:
    # 非个股查询：使用关键词匹配
    keywords = _extract_keywords(req.message)
    ...
```

## 诊断命令

### 快速健康检查

```bash
cd ~/learning-investment-strategies
.venv/bin/python -c "
from neo4j import GraphDatabase
from qing_investment.agent.config import settings

driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
with driver.session() as session:
    # 节点统计
    for label in ['Claim', 'Stock', 'Sector', 'Theme', 'Macro', 'Methodology']:
        result = session.run(f'MATCH (n:{label}) RETURN count(n) as c')
        print(f'{label}: {result.single()[\"c\"]}')
    
    # 关系统计
    for rel in ['ABOUT', 'SUPERSEDES', 'CONTRADICTS', 'CITED_IN', 'EXTRACTED_FROM']:
        result = session.run(f'MATCH ()-[r:{rel}]->() RETURN count(r) as c')
        print(f'{rel}: {result.single()[\"c\"]}')
    
    # claim_type 分布
    result = session.run('MATCH (c:Claim) RETURN c.claim_type as t, count(c) as c ORDER BY c DESC')
    print('\nClaim types:')
    for r in result:
        print(f'  {r[\"t\"]}: {r[\"c\"]}')

driver.close()
"
```

### 检查具体 claim 的关系

```bash
.venv/bin/python -c "
from neo4j import GraphDatabase
from qing_investment.agent.config import settings

driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
with driver.session() as session:
    # 查看某 claim 的所有关系
    result = session.run('MATCH (c:Claim {id: \"claim-20260603-001-a\"})-[r]->(target) RETURN type(r) as rel, labels(target)[0] as label, coalesce(target.name, target.code, target.path, \"\") as name')
    for r in result:
        print(f'{r[\"rel\"]} -> {r[\"label\"]}({r[\"name\"]})')
driver.close()
"
```

### 检查某股票关联的 claims

```bash
.venv/bin/python -c "
from neo4j import GraphDatabase
from qing_investment.agent.config import settings

driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
with driver.session() as session:
    result = session.run('MATCH (s:Stock {code: \"000066\"})<-[:ABOUT]-(c:Claim) RETURN c.id as id, c.subject as subject, c.claim_type as type')
    print('中国长城(000066) 关联的 claims:')
    for r in result:
        print(f'  {r[\"id\"]} [{r[\"type\"]}] {r[\"subject\"]}')
driver.close()
"
```

## 修复步骤（如需重新迁移）

### 步骤1：修复迁移脚本

确认 `scripts/migrate_claims_to_neo4j.py` 已包含以下修复：
- 第 243 行：`claim_type` 字段映射（支持 `claim_type` 和 `type` 双字段）
- 第 41 行：股票代码正则（支持 `.SH`/`.SZ` 后缀）
- 第 309-320 行：Stock 节点使用 `code` 属性

### 步骤2：清理旧数据并重新迁移

```bash
# 1. 关 Agent
kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null

# 2. 删除无 code 的 Stock 节点（旧错误节点）
cd ~/learning-investment-strategies
.venv/bin/python -c "
from neo4j import GraphDatabase
from qing_investment.agent.config import settings
driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
with driver.session() as session:
    session.run('MATCH (s:Stock) WHERE s.code IS NULL DETACH DELETE s')
driver.close()
"

# 3. 强制重新迁移
.venv/bin/python scripts/migrate_claims_to_neo4j.py --force-full

# 4. 重启 Agent
nohup .venv/bin/uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
```

### 步骤3：验证修复结果

运行【快速健康检查】命令，确认：
- Stock 节点 > 0
- Macro 节点 > 0
- Methodology 节点 > 0
- claim_type 分布多样（不全是 general）

## Neo4j vs Qdrant 的分工

| 场景 | 推荐后端 | 原因 |
|------|---------|------|
| 语义检索（用户问"MLCC怎么样"） | Qdrant | 向量相似度，无需精确关键词 |
| 个股关联 claims（用户问"000066"） | Neo4j | 图遍历 `:Claim-[:ABOUT]->:Stock` |
| Claim 演化追踪（观点是否被取代） | Neo4j | `SUPERSEDES`/`CONTRADICTS` 关系 |
| 板块关联分析（"半导体有哪些claims"） | Neo4j | `:Claim-[:ABOUT]->:Sector` |
| 全文关键词搜索 | Neo4j | `CONTAINS` 匹配 subject/statement |
| 跨主题关联发现 | Neo4j | 多跳图遍历（股票→板块→相关claims） |

## /chat 端点 Neo4j 查询策略

### 个股查询（有股票代码）

```python
# 优先使用图遍历
if fetched_stock_code:
    stock_claims = neo4j.get_claims_with_evolution(fetched_stock_code, limit=8)
    for c in stock_claims:
        claims.append(c)
```

**优势**：
- 精准匹配 `:Stock {code: '000066'}`，无噪音
- 返回 claims 的演化关系（被取代/矛盾）
- 时间排序（最新优先）

### 非个股查询（无股票代码）

```python
# 使用关键词匹配
keywords = _extract_keywords(req.message)
for kw in keywords[:3]:
    batch = neo4j.get_claims_by_keyword(kw, limit=5)
    for c in batch:
        claims.append(c)
```

**注意**：关键词匹配可能有噪音（如"中国"匹配到"中国石油"），需去重和限制数量。

## 关键教训

1. **字段命名一致性**：YAML 用 `claim_type`，代码中混用 `type` 和 `claim_type` 导致全部 fallback 到 `general`
2. **正则表达式要覆盖真实数据格式**：`.SH`/`.SZ` 后缀、无空格分隔、中文名称等
3. **图数据库的价值在关系遍历**：只用关键词匹配 = 浪费图结构，必须用 `:ABOUT`、`:SUPERSEDES`、`:CONTRADICTS`
4. **Primary entity 属性设计**：Stock 实体必须用 `code` 作为主键，`name` 作为辅助属性
5. **数据质量监控**：定期运行健康检查脚本，发现 0 个 Stock 节点立即告警
6. **迁移脚本需要单元测试**：`get_entity_type()`、`extract_stock_codes()` 等函数应有独立测试
