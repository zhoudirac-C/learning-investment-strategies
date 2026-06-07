# 方案C：Claim 增加 `intensity` 字段

> 目标：区分 UP "认真分析" vs "随口一提"，在检索阶段过滤低强度 claims，
> 解决"Neo4j 图遍历返回所有个股 claims、LLM 可能过度引用"的问题。

**创建日期**：2026-06-07  
**依赖**：无  
**关联问题**：向量库/图库个股节点泄漏到 prompt → LLM 把 UP 随口一提当作操作依据

---

## 一、总览：影响面矩阵

| 层 | 文件 | 改动类型 | 复杂度 |
|---|------|---------|--------|
| Schema | `src/qing_investment/claim_schema.py` | 新增字段+枚举 | 低 |
| 数据 | `knowledge/claims/*.yaml` (~540条) | 回填 intensity | **高** |
| Neo4j 迁移 | `scripts/migrate_claims_to_neo4j.py` | 新增属性+索引 | 低 |
| Neo4j 客户端 | `src/qing_investment/agent/tools/neo4j_client.py` | 查询增加 intensity 过滤 | 低 |
| Qdrant 索引 | `scripts/index_claims_to_qdrant.py` | payload 增加字段 | 低 |
| 检索节点 | `src/qing_investment/agent/graph/nodes.py` | 检索后 intensity boost/penalty | 中 |
| Chat 端点 | `src/qing_investment/agent/main.py` | prompt 中按 intensity 分级 | 中 |
| 时效模块 | `src/qing_investment/agent/tools/claim_freshness.py` | freshness × intensity 交叉评分 | 低 |
| 测试 | `tests/test_claim_schema.py` | 新增 intensity 校验用例 | 低 |
| **新增** | `scripts/backfill_claim_intensity.py` | 自动分类 + 人工 review 标记 | 中 |

---

## 二、任务拆分

### 任务 1：Schema 层——新增 `intensity` 字段 ✅ 已完成

**文件**：`src/qing_investment/claim_schema.py`

**改动**：

```python
# 新增枚举
VALID_INTENSITY = {"high", "medium", "low"}

# REQUIRED_FIELDS 新增
REQUIRED_FIELDS = {
    ...
    "intensity",        # ← 新增
}

# Claim dataclass 新增字段
@dataclass(frozen=True)
class Claim:
    ...
    intensity: str      # ← 新增，取值 high/medium/low

# validate_claim_dict 新增校验
_require_enum("intensity", data["intensity"], VALID_INTENSITY)

# Claim 构造新增
return Claim(
    ...
    intensity=str(data["intensity"]),
)
```

**验证**：`pytest tests/test_claim_schema.py -v` 应通过（测试用例稍后更新）

---

### 任务 2：测试层——更新 schema 测试用例 ✅ 已完成

**文件**：`tests/test_claim_schema.py`

**改动**：
- 在所有有效 claim fixture 中增加 `"intensity": "medium"`
- 新增测试：`test_invalid_intensity_rejected` — 传入 `"extreme"` 应抛 ValueError
- 新增测试：`test_missing_intensity_rejected` — 缺 intensity 字段应抛 ValueError

---

### 任务 3：数据层——回填 intensity 到现有 ~540 条 claims

**策略**：分两阶段——先自动分类，再人工 review。

#### 阶段 3A：自动分类脚本 ✅ 已完成

**新文件**：`scripts/backfill_claim_intensity.py`

**分类规则**（按优先级从高到低）：

```
Rule 1: claim_type = "methodology" | "operation" | "technical-knowledge"
  → intensity = "high"  (方法论/操作框架是 UP 核心体系，强度最高)

Rule 2: confidence = "high" AND (statement 包含 "确定性" | "一定要" | "必买" | "核心" | "主线" | "类比" | "格局")
  → intensity = "high"  (高置信度 + 强语言 → 认真分析)

Rule 3: source_type = "bilibili_video" | "bilibili_column"
  → intensity = "high"  (视频/专栏是 UP 精心准备的深度内容)

Rule 4: source_type = "bilibili_dynamic_repost" | evidence_quote 长度 < 30
  → intensity = "low"  (转发/一句话动态 → 随口一提)

Rule 5: subject 包含 6位数字股票代码 且 statement 长度 < 50
  → intensity = "low"  (盘中随口提某只票)

Rule 6: claim_type = "stock-view" AND confidence = "low"
  → intensity = "low"  (低置信度个股观点)

Rule 7: 默认
  → intensity = "medium"  (复盘提及、方向判断等)
```

**脚本行为**：
1. 遍历 `knowledge/claims/*.yaml`
2. 对每个 claim dict 应用规则，写入 `intensity` 字段
3. 输出统计：`high: X, medium: Y, low: Z, 未分类: 0`
4. 对规则不确定的 claim（无法匹配任何规则），写入 `intensity: "medium"` 并在 `interpretation` 末尾追加 `"[INTENSITY_AUTO: medium, review needed]"`
5. 生成 `logs/intensity_backfill_report.txt`，列出所有 `low` 和 `medium` 的 claims，供人工 review

**运行**：
```bash
cd ~/learning-investment-strategies
PYTHONPATH=src .venv/bin/python scripts/backfill_claim_intensity.py
```

#### 阶段 3B：人工 review

1. 打开 `logs/intensity_backfill_report.txt`
2. 逐条检查 `low` 的 claims——是否真的是随口一提？
3. 逐条检查 `high` 的 claims——是否有误判？
4. 对 `[INTENSITY_AUTO: medium, review needed]` 的 claims，手动判断并修改
5. 确认后删除 `interpretation` 中的 `[INTENSITY_AUTO: ...]` 标记

**注意**：回填完成后必须运行 schema 验证：
```bash
pytest tests/test_claim_schema.py -v
```

---

### 任务 4：Neo4j 迁移——新增 intensity 属性

**文件**：`scripts/migrate_claims_to_neo4j.py`

**改动位置 1**：`_migrate_single_claim()` 的 `CREATE (c:Claim {...})` 语句

在属性列表中增加：
```cypher
CREATE (c:Claim {
    ...
    intensity: $intensity,     -- ← 新增
})
```

在参数字典中增加：
```python
"intensity": claim.get("intensity", "medium"),
```

**改动位置 2**：索引创建

在约束/index 创建区块增加：
```python
session.run("CREATE INDEX claim_intensity IF NOT EXISTS FOR (c:Claim) ON (c.intensity)")
```

**运行**：
```bash
.venv/bin/python scripts/migrate_claims_to_neo4j.py --force-full
```

**验证**：
```cypher
MATCH (c:Claim) 
RETURN c.intensity, count(c) ORDER BY c.intensity
```
应返回 high/medium/low 三组的计数。

---

### 任务 5：Qdrant 索引——payload 增加 intensity

**文件**：`scripts/index_claims_to_qdrant.py`

**改动**：在 payload 字典中增加一行：

```python
payload={
    "claim_id": cid,
    ...
    "intensity": claim.get("intensity", "medium"),  # ← 新增
},
```

同时在 Neo4j 查询中增加 `intensity` 字段：
```python
result = session.run(
    "MATCH (c:Claim) RETURN c.id as id, ..., c.intensity as intensity"
)
```

**运行**：
```bash
PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_claims_to_qdrant.py
```

---

### 任务 6：Neo4j 客户端——查询增加 intensity 过滤

**文件**：`src/qing_investment/agent/tools/neo4j_client.py`

**改动**：`get_claims_about_stock()` 增加可选参数，过滤低强度：

```python
def get_claims_about_stock(
    self, stock_code: str, limit: int = 10, min_intensity: str | None = None
) -> list[dict]:
    query = """
    MATCH (c:Claim)-[:ABOUT]->(s:Stock {code: $stock_code})
    WHERE c.status IN ['active']
    """
    if min_intensity == "medium":
        query += " AND c.intensity IN ['high', 'medium']\n"
    elif min_intensity == "high":
        query += " AND c.intensity = 'high'\n"
    # min_intensity=None → 不过滤（向后兼容）
    
    query += """
    RETURN c.id as id, c.statement as statement,
           c.confidence as confidence, coalesce(c.source_date, '') as source_date,
           c.status as status, coalesce(c.subject, '') as subject,
           c.claim_type as claim_type, coalesce(c.intensity, 'medium') as intensity
    ORDER BY source_date DESC
    LIMIT $limit
    """
```

**同样修改** `get_claims_with_evolution()`。

---

### 任务 7：检索节点——retrieve_knowledge 增加 intensity boost

**文件**：`src/qing_investment/agent/graph/nodes.py`

**改动位置**：`retrieve_knowledge()` 函数，在 `_apply_claim_freshness` 之后增加：

```python
# ── Intensity boost/penalty（方案C）──
def _apply_intensity_weight(claims: list[dict], is_stock_query: bool) -> list[dict]:
    """对个股查询，低强度 claims 降权/过滤。"""
    for c in claims:
        intensity = c.get("intensity", "medium")
        if is_stock_query and intensity == "low":
            # 个股查询：low intensity 只保留标记，降权到末尾
            c["intensity_penalty"] = True
            c["_sort_key"] = c.get("days_ago", 999) + 365  # 排到最后
        elif intensity == "high":
            c["_sort_key"] = c.get("days_ago", 999) - 7  # boost（往前排7天）
        else:
            c["_sort_key"] = c.get("days_ago", 999)
    
    # Re-sort by _sort_key
    claims.sort(key=lambda x: x.get("_sort_key", 999))
    return claims

# 在 retrieve_knowledge 中调用：
claims = _apply_claim_freshness(claims)
claims = _apply_intensity_weight(claims, is_stock_query=bool(stock_code))
```

**关键设计决策**：
- 大盘/板块查询：intensity 不影响排序（只做标注），因为大盘分析走 `_filter_methodology_only`
- 个股查询：`intensity=low` 不直接丢弃（保留作为背景信息），但排到末尾 + 标记 `intensity_penalty=True`
- 排到末尾意味着 prompt 中只取前 N 条时，low 的 claims 大概率不会被注入

---

### 任务 8：Chat 端点——prompt 中按 intensity 分级

**文件**：`src/qing_investment/agent/main.py`

**改动**：在构建 `【UP最新观点】` / `【UP近期观点】` / `【UP历史观点】` 块时，对每条 claim 增加 intensity 标记：

```python
def _format_claim_line(c: dict) -> str:
    intensity = c.get("intensity", "medium")
    intensity_tag = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(intensity, "⚪")
    freshness = c.get("freshness_label", "")
    ...
    return f"- {intensity_tag} [{freshness}] {claim_line}"

# 个股查询时，额外过滤 low intensity
if is_stock_query:
    fresh_views = [c for c in fresh_views if c.get("intensity") != "low"]
```

**Prompt 指令增强**——在"引用纪律"部分增加：

```
14. 【intensity分级】claims 按 UP 分析深度分级：
    🔴 high = UP 专题分析/视频重点推荐 → 可引用，但必须配实时数据
    🟡 medium = UP 复盘提及/方向判断 → 参考价值中等
    ⚪ low = UP 盘中随口/转发 → 仅供参考，不得作为操作依据
```

---

### 任务 9：时效模块——freshness × intensity 交叉

**文件**：`src/qing_investment/agent/tools/claim_freshness.py`

**改动**：在 `apply_claim_freshness` 中为每条 claim 附加 intensity 信息，以便调用方能交叉使用：

```python
c_copy["intensity"] = c.get("intensity", "medium")
```

**不做**：不在 freshness 模块中做 intensity 过滤——过滤逻辑留在调用方（nodes.py / main.py），保持模块职责单一。

---

### 任务 10：全量重建索引

**顺序**：
```bash
# 1. 关 Agent
kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null

# 2. 回填 intensity（如果之前没做）
cd ~/learning-investment-strategies
PYTHONPATH=src .venv/bin/python scripts/backfill_claim_intensity.py

# 3. Neo4j 全量迁移
.venv/bin/python scripts/migrate_claims_to_neo4j.py --force-full

# 4. Qdrant 全量重建
PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate

# 5. 重启 Agent
nohup .venv/bin/uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
```

---

## 三、验收标准

### 功能验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| 1 | Schema 拒绝无效 intensity | `pytest tests/test_claim_schema.py -v` |
| 2 | 全部 claims 有 intensity 字段 | `grep -L "intensity:" knowledge/claims/*.yaml` 返回空 |
| 3 | Neo4j 有 intensity 属性和索引 | `MATCH (c:Claim) RETURN c.intensity, count(c)` |
| 4 | Qdrant payload 包含 intensity | 索引脚本输出 `✅ Integrity check passed` |
| 5 | 个股查询不返回 low intensity claims | 微信问 "000066走势" → prompt 中个股 claims 无 ⚪ 标记 |
| 6 | 方法论 claims 不受 intensity 过滤 | 大盘查询 → methodology claims 正常出现在 prompt 中 |
| 7 | 向后兼容 | 未配置 intensity 的服务仍正常运行（默认 medium） |

### 行为验收

| 场景 | 预期行为 |
|------|---------|
| 用户问个股 + UP 3天前视频重点推荐过 | claim 标记 🔴 high → 可引用，配实时数据 |
| 用户问个股 + UP 2天前盘中随口提了一句 | claim 标记 ⚪ low → 不进入 prompt 或排在末尾 |
| 用户问大盘方向 | 方法论 claims（全 high）正常进入 market_analyst |
| 用户问板块 | sector-theme claims 按 intensity 正常排序 |

---

## 四、风险与回滚

| 风险 | 缓解措施 |
|------|---------|
| 自动分类误判（low 标成 high 或反之） | 阶段 3B 人工 review；`backfill_report.txt` 可审计 |
| 重建索引时数据丢失 | `--force-recreate` 前备份 `.qdrant_data/` |
| Neo4j intensity 属性缺失导致查询报错 | `coalesce(c.intensity, 'medium')` 兜底 |
| 向后不兼容（老代码读不到 intensity） | 所有读取处都 fallback `c.get("intensity", "medium")` |

**回滚**：如果 intensity 字段引入后导致分析质量下降（如漏掉了有价值的 claim），只需：
1. 把所有代码中 `min_intensity` 参数改回 `None`
2. 移除 prompt 中的 intensity 标签
3. 不需要回滚数据（intensity 字段无害）

---

## 五、执行顺序

```
任务1 (schema) ──→ 任务2 (测试)
                      ↓
                 任务3A (自动回填)
                      ↓
                 任务3B (人工 review)  ←── 这是最耗时的步骤
                      ↓
          ┌───────────┴───────────┐
          ↓                       ↓
    任务4 (Neo4j)           任务5 (Qdrant)
          ↓                       ↓
          └───────────┬───────────┘
                      ↓
              任务6 (Neo4j client)
              任务7 (retrieve_knowledge)
              任务8 (/chat prompt)
              任务9 (freshness)
                      ↓
              任务10 (全量重建)
                      ↓
                 验收测试
```

**预估工时**：任务 1-2, 4-9 约 1-2 小时；任务 3（回填 + review）取决于 review 深度，预计 1-3 小时。
