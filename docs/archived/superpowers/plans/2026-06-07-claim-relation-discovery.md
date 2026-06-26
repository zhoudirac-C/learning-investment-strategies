# Claim 关系发现：方案1+3 实现计划

> **目标**：让 Neo4j 图里 Claim 之间的关系不再是"全靠人手工写"。
> **策略**：图遍历（免费）+ LLM 增量判断（精准）。

**创建日期**：2026-06-07

---

## 一、方案概述

| 方案 | 做什么 | 成本 |
|------|--------|------|
| 方案1 | 检索时用图遍历 `(Claim)-[:ABOUT]->(实体)<-[:ABOUT]-(Claim)` 发现相关 claims | 免费 |
| 方案3 | 新增 claim 时用 LLM 判断与 top-3 相似 claims 的关系 | 每 claim ~$0.001 |

---

## 二、任务拆分

### 任务 1：检索节点——图遍历补充相关 claims ✅

**文件**：`src/qing_investment/agent/graph/nodes.py`

在 `retrieve_knowledge()` 中，claims 检索完成后，对每条 claim 做一个轻量图遍历：

```python
# 取前 3 条 claims 的 ID，查 Neo4j 找到同实体相关 claims
related_claim_ids = set()
for c in claims[:3]:
    cid = c.get("id", "")
    if cid:
        related = neo4j.get_related_claims(cid, limit=5)
        for rc in related:
            rid = rc.get("id", "")
            if rid and rid not in seen_ids:
                related_claim_ids.add(rid)

# 查 Neo4j 拿全文
for rid in related_claim_ids:
    full = neo4j.get_claim_evolution(rid)
    if full and rid not in seen_ids:
        seen_ids.add(rid)
        claims.append(...)
```

**设计决策**：
- 只对 top-3 检索 claims 做图遍历（不是全量，避免噪音）
- 取同实体最多 5 条相关 claims
- 合并去重后走同一套 freshness+intensity 流水线

---

### 任务 2：Chat 端点——图遍历补充相关 claims ✅

**文件**：`src/qing_investment/agent/main.py`

在 `/chat` 的 claims 检索后，同样做图遍历补充：

```python
# 取 Qdrant 语义检索到的 claims ID，图遍历找同实体相关 claims
if claims:
    top_claim_ids = [c.get("id") for c in claims[:3] if c.get("id")]
    neo4j = Neo4jClient()
    seen_ids = set(c.get("id") for c in claims if c.get("id"))
    for cid in top_claim_ids:
        related = neo4j.get_related_claims(cid, limit=5)
        for rc in related:
            rid = rc.get("id")
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                claims.append(rc)
    neo4j.close()
```

---

### 任务 3：新增脚本——LLM 判断 Claim 间关系

**新文件**：`scripts/discover_claim_relations.py`

**流程**：
```
一条新 claim
  → embedding → Qdrant qing_claims 搜索 top-3 相似
  → 对每对 (新claim, 相似claim)，调用 LLM：
      "请判断以下两条 claim 之间的关系：
       A: [新 claim 全文]
       B: [相似 claim 全文]
       关系选项：supplements（补充）、contradicts（矛盾）、supersedes（取代）、none（无关）
       如果是取代，哪条取代哪条？"
  → 更新新 claim YAML 的 supersedes/contradicts 字段
```

**LLM prompt 模板**：
```
你是投资研究助手。请判断两条投资观点 claim 之间的关系。

Claim A（新）: {statement_a}
Claim B（已有）: {statement_b}

主题: {subject_a} vs {subject_b}
日期: {date_a} vs {date_b}

关系类型（选一个）：
- supersedes: A 取代了 B（A 是更新的判断，B 已过时）
- supplements: A 补充了 B（方向一致，A 增加了细节或标的）
- contradicts: A 与 B 矛盾（方向相反或判断冲突）
- none: 无直接关系

以 JSON 格式回复：
{"relation": "supersedes|supplements|contradicts|none", "reason": "简短说明"}
```

**运行**：
```bash
# 处理指定文件
.venv/bin/python scripts/discover_claim_relations.py --file knowledge/claims/claim-20260604-006.yaml

# 处理全部无关系的 claims
.venv/bin/python scripts/discover_claim_relations.py --all-missing

# 干跑（只输出判断，不写入）
.venv/bin/python scripts/discover_claim_relations.py --file xxx.yaml --dry-run
```

**成本估算**：
- 新增 claim 场景：每 claim 调 LLM 1 次（一次判断 top-3 对），约 $0.001
- 全量回填场景：566 条中约 500 条无关系 × $0.001 ≈ $0.50

---

### 任务 4：全量回填历史 claims 关系 ✅

运行 `discover_claim_relations.py --all-missing` 对所有 `supersedes=[]` 且 `contradicts=[]` 的 claims 做关系发现。

随后重建 Neo4j（`--force-full` + Qdrant）。

---

### 任务 5：Agent 检索集成 + 全量重建 ✅

1. 确保任务 1+2 的图遍历代码生效
2. 关 Agent → Neo4j full migration → Qdrant claims rebuild → 启动 Agent
3. 验证：查个股时 Agent 能返回同板块相关 claims

---

## 三、执行顺序

```
任务1 (nodes.py 图遍历) ──┬── 并行
任务2 (main.py 图遍历)  ──┘
              ↓
任务3 (discover_claim_relations.py 脚本)
              ↓
任务4 (全量回填历史 claims)
              ↓
任务5 (Neo4j + Qdrant 重建 + Agent 启动)
```

---

## 四、验收标准

| # | 验收项 |
|---|--------|
| 1 | 查"燃气轮机"方向 → Agent 返回杰瑞股份+中国动力+万泽股份等多只标的 claims |
| 2 | discover_claim_relations.py 正确识别矛盾/补充/取代关系 |
| 3 | 新 claim 写入后 YAML 自动填好 supersedes/contradicts |
| 4 | Neo4j 中 SUPERSEDES/CONTRADICTS 关系数从 25 条增长 |
