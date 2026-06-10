# MCP 工具驱动的轻量方向更新

> 会话来源：2026-06-10  
> 适用场景：用户要求基于 UP 最新观点更新观察池和策略配置，但不需要价格数据（非交易时段更新、纯方向调整）

## 与标准全量更新的区别

| | 标准全量更新 | 轻量方向更新 |
|---|---|---|
| 何时用 | 盘后、有实时价格 | 上午/盘中、纯方向调整 |
| Step 1（价格拉取） | 必须 | ❌ 跳过 |
| Step 2（UP 观点） | 读文件 + Qing-Agent | MCP Qdrant + Neo4j 优先 |
| Step 2.5（技术分析） | 必须 scan_all_stocks | ❌ 跳过（无价格） |
| Step 5（持仓风控） | 必须 | ❌ 跳过（无持仓变动） |
| Step 3-4（config 更新） | ✅ | ✅ |
| Step 6-7（验证+提交） | ✅ | ✅ |

## MCP 工具在 Step 2 的优势

传统 Step 2 流程：手动 `find knowledge/claims/` → 读 YAML → `knowledge/wiki/` → `sources/raw/`。耗时长且容易遗漏。

MCP 加速：
```python
# 语义搜索全量 claims（不仅文件名匹配，语义相关也能找到）
mcp_qdrant_search_claims("涨价逻辑 上游 材料 操作策略 清仓")

# 时间序列视图（按日期看 UP 操作基调演进）
mcp_neo4j_get_recent_claims(days=14)

# 精确关键词匹配（搜股票代码、板块名）
mcp_neo4j_search_claims_graph("MLCC")
```

## 执行要点

1. **必须确认不涉及具体价格**：在跳过 Step 1 之前，确认用户不是问"什么价格买入"
2. **strategy_pack 只改 direction/schedule/framework，不改 entry_points**：entry_points 需要价格支撑，没有价格数据时不生成
3. **使用 monitor_only 降级而非删除**：遵循 skill 核心纪律——不删除旧配置
4. **MCP 搜索结果交叉验证**：Qdrant 语义搜索 + Neo4j 精确匹配互相补位（语义覆盖广/精确不漏）

## 常见陷阱

### 陷阱 1：分析→配置的交叉校验缺失（2026-06-10 发现）

**症状**：Agent 在分析阶段列出了大量标的（含 UP 明确提到的方向），但执行 watchlist 更新时部分 UP 明确提到的标的被遗漏。

**根因**：
1. 某方向（如硅片）的信号分散在多个 claim 中（003-d、005-b、005-c、006-b），Agent 只聚焦最新一个 claim 导致漏判
2. 没有在 watchlist 更新后反向交叉校验"我刚才分析列出的标的都加进去了吗？"

**修复**：
- Step 3（更新 watchlist）完成后，**必须 grep 分析回复中出现的所有 UP 明确提及的股票代码**，与 watchlist 逐条对照
- 若发现分析中有但 watchlist 缺失的标的，分两类处理：
  - UP **直接点名**的方向/标的 → 必须加入（这是疏漏）
  - Agent **框架推理补充**的标的 → 标记"推理补充，UP 未直接点名"，可加可不加，需向用户说明

**反面案例（2026-06-10）**：Agent 分析中列出「12英寸硅片→立昂微(605358)、TCL中环(002129)」，UP 在 4 个 claim 中明确提到硅片最强分支，但 watchlist 更新时漏加。用户发现后追问原因。

### 陷阱 2：多 claim 方向信号聚合不足

**症状**：某方向在多个 claim 中被反复提及但从未成为单一 claim 的"主角"，导致 Agent 低估其重要性。

**修复**：在 MCP 查询阶段，对 `mcp_neo4j_get_recent_claims` 的结果做方向频次统计——同一关键词（如"硅片"）在 3+ 个 claims 中出现 → 视为 UP 持续强调的方向，强制进入 watchlist 检查流程。

## 实战案例（2026-06-10）

用户问："根据最近up的观点，我们的持仓池和观察池策略要做哪些更新"

流程：
1. `mcp_neo4j_get_recent_claims(days=14)` → 两周操作基调演进（5/24-6/10）
2. `mcp_qdrant_search_claims("操作 方向 主线 规避")` → 方向判断补充
3. 逐日 check 6/4→6/5→6/7→6/8→6/9→6/10 转折点
4. 结论：第三次修复，3个方向从 monitor_only → offensive
5. 用 Python `execute_code` 一次性修改 watchlist + strategy_pack
6. `validate_config.py` 验证
7. git commit + push

耗时：从 MCP 查询到 commit ~10 分钟（对比传统手动翻文件 ~30 分钟）
