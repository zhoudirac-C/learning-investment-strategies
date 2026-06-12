# 大盘分析方法论批量提取工作流

> 从 UP 历史早盘/复盘中系统提取市场分析方法论，写入 claims，用于后续归纳 framework。
> 完整方案见 `docs/plans/market-analysis-methodology-extraction-plan.md`

## 何时使用

触发词：`提取大盘方法`、`bulk extract`、`批量提取方法论`

## 四步流程

### Step 1: 初始化临时索引

扫描指定目录下的 raw 文件 → 按 pub_date 排序 → 写入 `methodology_extraction_index.json`（所有 status=pending），同时初始化 `methodology_claims_index.md`（空模板）。

### Step 2: 逐篇提取（分批次，每批 10-20 篇）

对每篇 pending 文件：

1. **读 raw 全文**
2. **识别大盘方法论**（L1-L4 四层维度）：
   - L1: 多级别顶底（120/90/60/30分钟）、钝化vs结构、九转序列、波浪修正
   - L2: 全A趋势结构、中阳线确认信号、量能阈值、下跌模式
   - L3: 三指数共振/背离、微盘股破位对主线压制
   - L4: 情绪锚点、跌停阈值、双冰点、假摔判断
3. **去重**：Qdrant 语义搜索 + Neo4j 关键词搜索已有 claims
   - 已存在 → 记录为 "referenced"，不新建
   - 需修改/拆分 → 标注 "modified"
   - 新方法论 → 走 Step 4 新建
4. **写 claim**：`claim_type=methodology/technical-signal`, `timeframe=permanent`
5. **gate_validate_claims.py 验证**
6. **双向记录**：
   - `methodology_extraction_index.json`: status=done, claims_extracted, methodology_tags
   - `methodology_claims_index.md`: 追加到 L1-L4 对应分类

### Step 3: 知识库同步

Phase 2 完成后（有新 claim 或修改已有 claim）必须跑：
`discover → Neo4j migrate → Qdrant rebuild → restart Agent`

### Step 4: 归纳总结

从 `methodology_claims_index.md` 读取所有 claims → 写两份文档：
- `knowledge/wiki/投资方法论/大盘分析方法论.md` — 完整方法论参考（含溯源）
- `framework/market-breadth-framework.md` — qing-agent 可执行 playbook（流程化）

## 方法论 vs 观点应用的边界

| 表述 | 分类 | 原因 |
|------|------|------|
| "60分钟底部结构形成才是纠错信号" | ✅ 方法论 | 脱离具体日期，任何时间适用 |
| "今天60分钟底部钝化消失，反弹弱" | ❌ 观点应用 | 绑定当日，不可复用 |
| "全A中阳线是建仓唯一信号" | ✅ 方法论 | 可泛化 |
| "今日全A指数收-0.3%，弱修复" | ❌ 观点应用 | 当日数据 |

## 关键经验（2026-06-12 实战）

- **范围限制**：仅早盘+复盘（190 篇），不包含盘中动态/午盘/周复盘。那些通过标准 ingestion 管线处理，它们的 methodology 会在 Phase 3.5 改造后被后续 ingestion 的 Step 6 自动捕获。
- **命中率**：190 篇 → 23 篇有方法论（12.1%）→ 25 条新 claims。大部分是板块/个股分析，不要因为没有方法论而沮丧。
- **双文档追踪**：`methodology_extraction_index.json`（进度追踪）+ `methodology_claims_index.md`（Phase 3 汇总用）。两个文档要同步更新，缺一不可。
- **方法论密度不均**：1-3月密集（框架成型期），4月真空（上升趋势无结构判断需求），5月回升。
- **L3（微盘股联动）是后期产物**：只在6/4之后出现。这不是遗漏——UP的方法论体系是逐步演化的，早期的框架中这部分自然不存在。
- **分批次执行**：每批 10-20 篇，断点可续。索引文件确保失败后不重复工作。
- **去重是最高频操作**：大量早期方法论在后续文档中被更精确地表述。先 Qdrant 语义搜索 → 再 Neo4j 关键词 → 确认无重复再建新 claim。
- **知识库同步不可跳过**：Phase 2 完成后有新 claim，必须跑 `discover → Neo4j → Qdrant → restart`。否则 Phase 3 归纳时 claims 不在向量库中，无法验证完整性。
- **临时索引生命周期**：Phase 1 创建 → Phase 2 逐批更新 → Phase 5 删除。方法论汇总文档（`methodology_claims_index.md`）保留，不删除。
