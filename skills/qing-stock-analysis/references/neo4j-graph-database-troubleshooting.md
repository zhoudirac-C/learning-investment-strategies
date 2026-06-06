# Neo4j 图数据库诊断与修复手册

## 背景

2026-06-06 用户质疑 Qing-Agent 的推理框架是否只能针对单一方向投资思路。深入排查后发现，Neo4j 图数据库存在严重数据质量问题，导致 claims 的关系图谱价值未发挥。

## 当前状态快照（2026-06-06）

| 指标 | 数值 | 健康标准 | 状态 |
|------|------|---------|------|
| Claims 节点 | 540 | — | ✅ |
| 关系总数 | 1,105 | — | ✅ |
| SUPERSEDES 关系 | 18 | 应有数百条 | ❌ 严重不足 |
| CONTRADICTS 关系 | 7 | 应有数十条 | ❌ 严重不足 |
| Stock 节点 | **0** | 应有数百个 | ❌ **严重缺失** |
| Macro 节点 | **0** | 应有数十个 | ❌ **严重缺失** |
| Methodology 节点 | **0** | 应有数十个 | ❌ **严重缺失** |
| Sector 节点 | 28 | — | ⚠️ 偏少 |
| Theme 节点 | 465 | — | ⚠️ 过多（应为实体节点） |
| claim_type | 全部 `general` | 应有多种类型 | ❌ **未分类** |

## 根因分析

### 根因1：字段映射错误（claim_type vs type）

**位置**：`scripts/migrate_claims_to_neo4j.py` 第 243 行

**错误代码**：
```python
"claim_type": claim.get("type", "general"),  # 读取的是 "type" 字段
```

**问题**：Claims YAML 中使用的是 `type` 字段（如 `type: stock-view`），但 Neo4j 查询时检查的是 `claim_type` 字段。由于 `type` 被正确写入，但 `get_entity_type()` 函数接收的是 `claim_type` 参数（永远为 `general`），导致所有实体都被标记为 `Theme`。

**影响**：
- `get_entity_type("general", subject)` 返回 `Theme`（fallback）
- 所有实体节点都是 `:Theme` 标签
- `:Stock`、`:Macro`、`:Methodology` 标签永不被创建

**修复**：
```python
# 第 243 行：统一使用 type 字段
"claim_type": claim.get("type", "general"),
# 第 282 行：get_entity_type 接收 type 而非 claim_type
entity_label = get_entity_type(claim.get("type", ""), subject)
```

### 根因2：股票代码提取正则缺陷

**位置**：`scripts/migrate_claims_to_neo4j.py` 第 41 行

**错误代码**：
```python
STOCK_CODE_RE = re.compile(r"\b(\d{6})\b")
```

**问题**：
1. Claims 中的股票代码可能带 `.SH`/`.SZ` 后缀（如 `000066.SZ`），正则无法匹配
2. 中文文本中股票代码前后可能没有单词边界（如"中国长城000066走势"）
3. 部分 claims 只提股票名称不提代码

**影响**：Stock 节点数量为 0

**修复**：
```python
# 支持 .SH/.SZ 后缀和前后无空格的情况
STOCK_CODE_RE = re.compile(r"\b(\d{6})(?:\.SH|\.SZ|\.sh|\.sz)?\b")
# 或更宽松：
STOCK_CODE_RE = re.compile(r"(?<![\d])(\d{6})(?![\d])")
```

### 根因3：SUPERSEDES/CONTRADICTS 关系缺失

**位置**：`scripts/migrate_claims_to_neo4j.py` 第 338-399 行（`migrate_relations()`）

**问题**：
1. 关系迁移是独立步骤，可能在 claims 迁移后未执行
2. YAML 中 `supersedes`/`contradicts` 字段可能为空或格式不一致
3. `migrate_relations()` 遍历所有 claims 文件重建关系，但没有增量机制

**检查方法**：
```bash
# 查看哪些 claims 有 supersedes/contradicts 字段
grep -l "supersedes:\|contradicts:" knowledge/claims/*.yaml | wc -l
```

### 根因4：/chat 端点未使用图遍历

**位置**：`src/qing_investment/agent/main.py` 第 149-168 行

**问题**：
- `/chat` 只用了 `get_claims_by_keyword()`（关键词匹配）
- 没有用 `get_claims_about_stock()`（图遍历）
- 没有用 `get_claim_evolution()`（关系追踪）

**当前做法**：
```python
# 关键词匹配——噪音大
for kw in keywords[:3]:
    batch = neo4j.get_claims_by_keyword(kw, limit=5)
```

**应使用**：
```python
# 个股查询——图遍历
if stock_code:
    claims = neo4j.get_claims_about_stock(stock_code, limit=10)
    # 追踪 claim 演化
    for c in claims:
        evolution = neo4j.get_claim_evolution(c["id"])
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
    print('\\nClaim types:')
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
    result = session.run('''
        MATCH (c:Claim {id: \"claim-20260603-001-a\"})-[r]->(target)
        RETURN type(r) as rel, labels(target)[0] as label, 
               coalesce(target.name, target.code, target.path, \"\") as name
    ''')
    for r in result:
        print(f'{r[\"rel\"]} -> {r[\"label\"]}({r[\"name\"]})')
driver.close()
"
```

## 修复步骤

### 步骤1：修复迁移脚本

1. 修改 `scripts/migrate_claims_to_neo4j.py`：
   - 第 243 行：`claim_type` 字段映射
   - 第 41 行：股票代码正则
   - 第 282 行：`get_entity_type()` 参数

2. 验证修复：
```bash
# 测试实体类型识别
.venv/bin/python -c "
from scripts.migrate_claims_to_neo4j import get_entity_type
print(get_entity_type('stock-view', '中国长城'))  # 应输出 Stock
print(get_entity_type('market-cycle', '上证指数'))  # 应输出 Macro
print(get_entity_type('methodology', '操作策略'))  # 应输出 Methodology
"
```

### 步骤2：重新迁移（增量）

```bash
# 1. 关 Agent
kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null

# 2. 强制重新迁移（会删除旧 claims 并重建）
cd ~/learning-investment-strategies
.venv/bin/python scripts/migrate_claims_to_neo4j.py --force-full

# 3. 重建关系
.venv/bin/python -c "
from scripts.migrate_claims_to_neo4j import migrate_relations
migrate_relations()
"

# 4. 重启 Agent
nohup .venv/bin/uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
```

### 步骤3：验证修复结果

运行【快速健康检查】命令，确认：
- Stock 节点 > 0
- Macro 节点 > 0  
- Methodology 节点 > 0
- claim_type 分布多样（不全是 general）

### 步骤4：增强 /chat 端点的图查询

修改 `src/qing_investment/agent/main.py`：

```python
# 个股查询时优先使用图遍历
if fetched_stock_code:
    stock_claims = neo4j.get_claims_about_stock(fetched_stock_code, limit=10)
    for c in stock_claims:
        cid = c.get("id")
        if cid and cid not in seen_ids:
            seen_ids.add(cid)
            claims.append(c)
            # 追踪 claim 演化（被取代/矛盾）
            evolution = neo4j.get_claim_evolution(cid)
            for e in evolution:
                if e.get("new"):
                    claims.append({...})  # 添加最新版本
```

## Neo4j vs Qdrant 的分工

| 场景 | 推荐后端 | 原因 |
|------|---------|------|
| 语义检索（用户问"MLCC怎么样"） | Qdrant | 向量相似度，无需精确关键词 |
| 个股关联 claims（用户问"000066"） | Neo4j | 图遍历 `:Claim-[:ABOUT]->:Stock` |
| Claim 演化追踪（观点是否被取代） | Neo4j | `SUPERSEDES`/`CONTRADICTS` 关系 |
| 板块关联分析（"半导体有哪些claims"） | Neo4j | `:Claim-[:ABOUT]->:Sector` |
| 全文关键词搜索 | Neo4j | `CONTAINS` 匹配 subject/statement |
| 跨主题关联发现 | Neo4j | 多跳图遍历（股票→板块→相关claims） |

## 关键教训

1. **字段命名一致性**：YAML 用 `type`，Neo4j 用 `claim_type`，代码中混用导致全部 fallback 到 `general`
2. **正则表达式要覆盖真实数据格式**：`.SH`/`.SZ` 后缀、无空格分隔、中文名称等
3. **图数据库的价值在关系遍历**：只用关键词匹配 = 浪费图结构，必须用 `:ABOUT`、`:SUPERSEDES`、`:CONTRADICTS`
4. **数据质量监控**：定期运行健康检查脚本，发现 0 个 Stock 节点立即告警
5. **迁移脚本需要单元测试**：`get_entity_type()`、`extract_stock_codes()` 等函数应有独立测试
