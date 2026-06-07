# Claim Intensity System

> 方案C实现。2026-06-07部署。

## 概述

在 claims 中新增 `intensity` 字段（high/medium/low），区分 UP "认真分析" vs "随口一提"。保护在**检索阶段**而非写入阶段——所有 claims 全量写入 Neo4j/Qdrant，检索时按 intensity 过滤/boost。

## 数据分布

| 等级 | 数量 | 占比 | 含义 |
|------|------|------|------|
| 🔴 high | 444 | 79.1% | UP 专题分析/视频重点推荐 |
| 🟡 medium | 115 | 20.5% | UP 复盘提及/方向判断 |
| ⚪ low | 2 | 0.4% | 纯随口（"要谨慎""大概率能反复"） |

## 架构层级

```
写入阶段（无过滤）
  claim YAML → migrate_claims_to_neo4j.py → Neo4j (c.intensity)
  Neo4j → index_claims_to_qdrant.py → Qdrant payload.intensity

检索阶段（三层防护）
  1. Neo4j: get_claims_about_stock(min_intensity="medium") 过滤 low
  2. nodes.py: _apply_intensity_weight() — 个股查询 low→+365天排末尾
  3. main.py: /chat prompt — 个股查询过滤 low，标注 🔴🟡⚪ + 规则14
```

## 相关文件

- `src/qing_investment/claim_schema.py` — VALID_INTENSITY 枚举 + 字段校验
- `scripts/backfill_claim_intensity.py` — 自动分类脚本（8条规则）
- `scripts/migrate_claims_to_neo4j.py` — Neo4j intensity 属性 + 索引
- `scripts/index_claims_to_qdrant.py` — Qdrant payload intensity
- `src/qing_investment/agent/tools/neo4j_client.py` — min_intensity 参数
- `src/qing_investment/agent/graph/nodes.py` — _apply_intensity_weight()
- `src/qing_investment/agent/main.py` — /chat intensity 分级标签
- `src/qing_investment/agent/tools/claim_freshness.py` — 透传 intensity

## 回填脚本规则

```
1. methodology/operation/technical-knowledge → high
2. confidence=high + 强语言关键词 → high
3. 视频/复盘/专栏/深度/早盘 source → high
4. 转发/repost → low
5. stock_code + 短statement → low
6. stock-view + confidence=low → low
7. evidence_quote<30 + interpretation<50 → low
8. 默认 → medium
```

## 验收方法

```bash
# Schema 测试
pytest tests/test_claim_schema.py -v

# Neo4j 分布
MATCH (c:Claim) RETURN c.intensity, count(c)

# Qdrant 完整性
python scripts/index_claims_to_qdrant.py --force-recreate
```
