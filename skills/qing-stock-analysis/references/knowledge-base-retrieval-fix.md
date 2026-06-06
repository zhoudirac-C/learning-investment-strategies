# 持仓数据注入与知识库检索规范

## 背景

2026-06-06 用户反馈 Qing-Agent 个股分析"没有学到UP的方法"，核心问题是知识库内容虽然存在，但 `/chat` 端点没有正确检索和注入。

## 知识库检索的常见问题

### 问题1：过滤条件错误

**错误做法：**
```python
# 只检索 framework/ 开头的内容
methodology_wiki = [
    s for s in wiki_snippets
    if s.get("source", "").startswith("framework/")
]
```

**问题**：`knowledge/` 下没有 `framework/` 目录，永远匹配不到。

**正确做法：**
```python
all_wiki = [
    s for s in wiki_snippets
    if s.get("source", "").startswith(("knowledge/wiki/", "framework/"))
]
```

### 问题2：Claims过滤太窄

**错误做法：**
```python
# 只保留方法论关键词
methodology_claims = []
for c in claims:
    stmt = (c.get("statement") or "").lower()
    if any(kw in stmt for kw in ["框架", "周期", "方法论", ...]):
        methodology_claims.append(c)
```

**问题**：个股相关的 claims（如"中国长城是信创核心标的"）被过滤掉了。

**正确做法：**
```python
all_claims = claims  # 不过滤，让LLM自己判断相关性
```

### 问题3：Claims未索引到Qdrant

**问题**：claims 只在 Neo4j，没在 Qdrant，语义检索不到。

**修复：**
```bash
.venv/bin/python scripts/index_claims_to_qdrant.py --force-full
```

### 问题4：持仓数据未注入

**问题**：分析个股时没有读取 `positions.yaml`，持仓建议没有结合成本/仓位。

**修复：**
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

## Prompt注入结构

正确的 prompt 应该按以下顺序注入数据：

```
【实时行情数据】（✅ 主要分析依据）
- 个股/指数行情: ...
- 个股历史K线（近90日）: ...
- 个股当日分时: ...
- 板块数据: ...

【博主知识库】（Wiki专题分析、投资方法论、市场复盘等）
- [Wiki] 市场分析/AI电源与超级电容: ...
- [Wiki] 投资方法论/周期判断: ...

【博主历史观点卡】（⚠️ 历史观点，仅供参考，不得作为当前判断依据）
- claim-xxx (2026-05-18): ...

【用户持仓数据】（如适用）
- 标的: 中国长城(000066)
- 持仓: 400股
- 成本: 18.074元
- 风控线: 15.8-16.0
- 减仓区: 17.5-18.0

【用户历史记忆】
- ...
```

## 重新索引知识库SOP

### 全量重建

```bash
# 1. 关Agent（Qdrant本地模式需要独占锁）
kill $(pgrep -f "uvicorn.*qing_investment") 2>/dev/null

# 2. 清空旧数据 + 全量索引
cd ~/learning-investment-strategies
rm -rf .qdrant_data .index_state.json
PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_documents_to_qdrant.py

# 3. 同步claims embedding
.venv/bin/python scripts/index_claims_to_qdrant.py --force-full

# 4. 重启Agent
nohup .venv/bin/uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
```

### 增量同步

```bash
PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_documents_to_qdrant.py
.venv/bin/python scripts/index_claims_to_qdrant.py
```

## 关键教训

1. **过滤条件必须验证**：`source.startswith("framework/")` 在目录不存在时永远为空
2. **Claims必须索引到Qdrant**：Neo4j只支持图查询，不支持语义检索
3. **持仓数据必须显式注入**：LLM不会自动知道用户持仓
4. **Qdrant本地模式有bug**：1.18.0的`query_points`对2D向量处理有问题，需要fallback
5. **知识库是方法论，不是信息来源**：claims是历史观点，不能作为当前判断依据
