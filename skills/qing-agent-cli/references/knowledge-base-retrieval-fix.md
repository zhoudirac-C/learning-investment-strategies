# 知识库检索修复记录（2026-06-06）

## 问题：/chat 端点检索不到知识库内容

### 现象
用户反馈："改了以后感觉没有用上知识库和项目里方法论"，分析输出"完全没学到UP的方法"。

### 根因分析

| 问题 | 现状 | 影响 |
|------|------|------|
| Wiki过滤条件错误 | `source.startswith("framework/")` | `framework/` 目录不存在，永远匹配不到 |
| Claims过滤太窄 | 只保留含"框架/周期/方法论"关键词 | 个股相关的claims被过滤 |
| Claims未索引到Qdrant | 只在Neo4j，没在Qdrant | 语义检索不到claims |
| 持仓数据未注入 | 未读取positions.yaml | 持仓建议没有结合成本/仓位 |

### 知识库现状

```
knowledge/
├── wiki/市场分析/          # 32个md（AI电源、CPU、MLCC等）→ 已索引到qing_knowledge
├── wiki/投资方法论/        # 10个md → 已索引
├── wiki/每日复盘/          # 19个md → 已索引
├── claims/*.yaml           # 89个yaml → 已索引到qing_claims
└── framework/              # ❌ 目录不存在
```

### 修复内容

#### 1. 放宽Wiki过滤（main.py）

**之前：**
```python
methodology_wiki = [
    s for s in wiki_snippets
    if s.get("source", "").startswith("framework/") or "投资方法论" in s.get("source", "")
]
```

**之后：**
```python
all_wiki = [
    s for s in wiki_snippets
    if s.get("source", "").startswith(("knowledge/wiki/", "framework/"))
]
```

#### 2. 保留所有Claims（main.py）

**之前：**
```python
methodology_claims = []
for c in claims:
    stmt = (c.get("statement") or "").lower()
    if any(kw in stmt for kw in ["框架", "周期", "方法论", ...]):
        methodology_claims.append(c)
```

**之后：**
```python
all_claims = claims  # 不过滤，让LLM自己判断相关性
```

#### 3. 索引Claims到Qdrant

```bash
.venv/bin/python scripts/index_claims_to_qdrant.py --force-full
# → Indexed 540 claims into Qdrant collection 'qing_claims'
```

#### 4. 同时检索两个集合（main.py）

```python
# 检索wiki和raw文档
results = qdrant.search(vec, collection="qing_knowledge", limit=8)

# 检索结构化claims
claim_results = qdrant.search(vec, collection="qing_claims", limit=8)
for r in claim_results:
    claims.append({
        "id": payload.get("claim_id", ""),
        "statement": payload.get("statement", ""),
        "subject": payload.get("subject", ""),
        "source_date": payload.get("source_date", ""),
        "confidence": payload.get("confidence", ""),
        "score": r.get("score", 0),
    })
```

#### 5. 注入持仓数据（main.py）

```python
if fetched_stock_code:
    # 从positions.yaml读取匹配持仓
    for account in positions_data.get("accounts", []):
        for pos in account.get("positions", []):
            code = pos.get("code", "").replace(".SZ", "").replace(".SH", "")
            if code == fetched_stock_code and pos.get("shares", 0) > 0:
                position_data = {
                    "account": account.get("name", ""),
                    "name": pos.get("name", ""),
                    "code": code,
                    "shares": pos.get("shares", 0),
                    "cost": pos.get("cost", 0),
                    "risk_line": pos.get("risk_line", ""),
                    "risk_zone": pos.get("risk_zone", ""),
                    "reduce_zone": pos.get("reduce_zone", ""),
                    "notes": pos.get("notes", ""),
                }
```

### Prompt注入结构

```
【实时行情数据】（✅ 主要分析依据）
...

【博主知识库】（Wiki专题分析、投资方法论、市场复盘等）
- [Wiki] 市场分析/AI电源与超级电容: ...
- [Wiki] 投资方法论/周期判断: ...

【博主历史观点卡】（⚠️ 历史观点，仅供参考）
- claim-xxx (2026-05-18): ...

【用户持仓数据】
- 标的: 中国长城(000066)
- 持仓: 400股
- 成本: 18.074元
- 风控线: 15.8-16.0
- 减仓区: 17.5-18.0
```

## QdrantClientWrapper修复

### 问题：Qdrant 1.18.0本地模式query_points有bug

当传入2D向量（embedding返回`(1, 512)`）时，`query_points`报错：
```
only integer scalar arrays can be converted to a scalar index
```

### 修复：添加向量维度归一化 + 手动fallback

```python
def search(self, query_vector, collection="qing_knowledge", limit=5):
    import numpy as np
    
    # 确保1D
    if hasattr(query_vector, 'ndim'):
        query_vec = np.array(query_vector).flatten()
    else:
        query_vec = np.array(query_vector).flatten()
    
    if self._is_local:
        try:
            resp = self._client.query_points(
                collection_name=collection,
                query=query_vec.tolist(),
                limit=limit,
                with_payload=True,
            )
            return [...]
        except Exception:
            # Fallback: manual cosine similarity
            return self._search_manual(query_vec, collection, limit)
    else:
        # Remote mode
        ...

def _search_manual(self, query_vec, collection, limit):
    """Manual cosine similarity for local mode fallback."""
    import numpy as np
    
    # Scroll all points
    all_points = []
    offset = None
    while True:
        resp = self._client.scroll(
            collection_name=collection,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        points = resp[0]
        if not points:
            break
        all_points.extend(points)
        offset = resp[1]
        if offset is None:
            break
    
    # Calculate cosine similarity
    scores = []
    query_norm = np.linalg.norm(query_vec)
    for p in all_points:
        vec = np.array(p.vector).flatten()
        score = np.dot(query_vec, vec) / (query_norm * np.linalg.norm(vec))
        scores.append((score, p))
    
    # Sort and return top-k
    scores.sort(key=lambda x: -x[0])
    return [
        {"id": p.id, "score": score, "payload": p.payload or {}}
        for score, p in scores[:limit]
    ]
```

## 重新索引知识库SOP

### 全量重建（数据损坏/模型升级/首次部署）

```bash
# 1. 关Agent（Qdrant本地模式需要独占锁）
kill $(pgrep -f "uvicorn.*qing_investment") 2>/dev/null

# 2. 清空旧数据 + 全量索引（预计15-25分钟，560个文件）
cd ~/learning-investment-strategies
rm -rf .qdrant_data .index_state.json
PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_documents_to_qdrant.py

# 3. 同步claims embedding
.venv/bin/python scripts/index_claims_to_qdrant.py --force-full

# 4. 重启Agent
nohup .venv/bin/uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
```

### 增量同步（日常新增文档后）

```bash
# 无需--force-full，只处理新/修改的文件
PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_documents_to_qdrant.py
.venv/bin/python scripts/index_claims_to_qdrant.py
```

## 关键教训

1. **过滤条件必须验证**：`source.startswith(