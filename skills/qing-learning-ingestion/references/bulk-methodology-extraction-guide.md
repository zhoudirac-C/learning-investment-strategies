# 大盘方法论批量提取指南

> 从大量历史 raw 文件中系统提取市场分析方法论的模式。2026-06-12 会话中验证。

## 适用场景

- 批量回填历史文档中的方法论内容
- 新建知识领域后，从已有文档中补充相关知识

## 文件结构

```
config/stock_monitor/
├── methodology_extraction_index.json   # 进度追踪（临时，完成后删除）
└── methodology_claims_index.md         # 方法论 claims 汇总（永久保留）
```

## 进度索引格式

```json
{
  "version": "2.0",
  "scope": "早盘+复盘 only",
  "total_files": 190,
  "files": {
    "文件名.md": {
      "status": "pending|done|skipped",
      "pub_date": "2026-01-05",
      "claims_extracted": ["claim-YYYYMMDD-NNN-x"],
      "methodology_tags": ["L1_指数结构"],
      "skip_reason": "sector analysis only"
    }
  },
  "methodology_categories": {
    "L1_指数结构": {"claims": [], "description": "多级别顶底、钝化vs结构、九转序列、波浪修正"},
    "L2_全A广度": {"claims": [], "description": "全A趋势结构、中阳线信号、量能阈值"},
    "L3_微盘联动": {"claims": [], "description": "三指数共振/背离、微盘股破位压制"},
    "L4_情绪判断": {"claims": [], "description": "情绪锚点、跌停阈值、分歧修复"}
  }
}
```

## L1-L4 四层分类体系

| 层级 | 关键词（文件名/内容匹配） | claim_type |
|------|------------------------|-----------|
| L1 指数结构 | 分钟、钝化、结构、顶、底、序列、低9、高9、波浪、纠错 | methodology / technical-signal |
| L2 全A广度 | 全A、中阳线、量能、万亿、缩量、放量、地量、振幅 | methodology / market-cycle |
| L3 微盘联动 | 微盘、背离、共振、大小盘、压制、同步 | methodology |
| L4 情绪判断 | 跌停、涨停、连板、冰点、分歧、修复、情绪、红盘 | methodology / market-cycle |

## 逐篇处理流程

```
Step 1: 读 raw 全文
Step 2: 识别大盘分析方法论（L1-L4 维度）
Step 3: 去重 — Qdrant 语义搜索 + Neo4j 关键词搜索
        - 已存在 → 标注 referenced，不新建
        - 需修改/拆分 → 修改已有 claim，标注 modified
        - 新方法论 → 走 Step 4
Step 4: 写 claim（claim_type=methodology/technical-signal, timeframe=permanent）
Step 5: gate_validate_claims.py 验证
Step 6: 更新两个文件：
        a. methodology_extraction_index.json（进度）
        b. methodology_claims_index.md（汇总）
```

## 提取边界：什么算方法论

**✅ 提取**（可脱离当天市场环境独立使用）：
- "60分钟顶部钝化消失=短期无高点" → 可泛化
- "跌停降至5家以下=做空情绪释放完毕" → 可复用
- "全A中阳线是建仓唯一信号" → 方法论

**❌ 不提取**（单日特定判断）：
- "今天全A跌0.3%，弱修复" → 观点应用
- "明天看美股脸色" → 太笼统

## 分批次执行策略

- 每批 20 篇，断点可续
- 统计 done/skipped/新建 claims
- 每批后更新汇总文档

## 完成后

1. 用 methodology_claims_index.md 归纳 → `大盘分析方法论.md` + `market-breadth-framework.md`
2. 运行 knowledge base sync（discover → Neo4j → Qdrant）
3. 删除 methodology_extraction_index.json（临时索引）
4. 保留 methodology_claims_index.md（供后续增量合并）
