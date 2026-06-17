# qing-fupan-morning-usage Skill 修复计划

> 审计日期：2026-06-17
> 审计范围：`skills/qing-fupan-morning-usage/SKILL.md` + 关联代码/config
> 触发：用户要求全局核对 skill 是否完善

---

## 问题清单（12项）

### 🔴 P0 — 阻断性

| # | 位置 | 问题 | 修复方案 |
|:--|:-----|:-----|:-----|
| 1 | `gates.py:127-128` vs `direction_pool.yaml` | MLCC 用 `divergence_verification`、商业航天用 `catalyst_window`，SectorGate 不认识，两个方向被静默拦截 | 方案A：改 config 为标准值（推荐，改动小）<br>方案B：扩展 SectorGate.STAGE_ACTIONABLE |
| 2 | skill line 51 | 数据路径写错：`sources/original/bilibili/` | 改为 `sources/raw/财经/` |

### 🟡 P1 — Skill 设计/内容问题

| # | 位置 | 问题 | 修复方案 |
|:--|:-----|:-----|:-----|
| 3 | skill 整体定位 | 把自己定位成"从零提取"，实际应该是 claims 下游消费者 | 改输入源：从"读原始文件"改为"用 mcp 工具查已有 claims" |
| 4 | skill 底部引用 | 未声明依赖 Qdrant/Neo4j，skill 缺少 mcp 工具使用说明 | 补充：`mcp_qdrant_search_claims` / `mcp_qdrant_search_knowledge` / `mcp_neo4j_get_claim_relations` |
| 5 | skill §Config 变更纪律 | 级联更新步骤只列了 4 步，缺 cron prompt 更新 + 框架条件清理 | 补充 2 步：更新所有 cron task prompt + 移除已兑现的框架条件 |
| 6 | skill 无 | 方向数量过时（"12个"→ 实际21个） | 更新为"21个活跃方向"或去掉具体数字 |
| 7 | skill 无 | 未提及 watchlist.yaml 仍并行运行 | 加一段说明新旧系统关系，明确迁移路径 |

### 🟢 P2 — 操作便利性

| # | 位置 | 问题 | 修复方案 |
|:--|:-----|:-----|:-----|
| 8 | skill §每日操作清单 | 只有"读XX→更新YY"，缺少具体执行命令 | 补充 mcp 调用示例 + patch 命令 |
| 9 | skill §每日操作清单 | 未与 cron 体系（14:00/14:30/14:50/17:00）联动 | 加一段 cron 联动说明 |

### 🟢 P3 — 代码层（已修复 ✅）

| # | 位置 | 问题 | 状态 |
|:--|:-----|:-----|:----:|
| 10 | `BuySignalRuleEngine` | pre_condition 检查未实现，三重过滤缺代码拦截 | ✅ 已修复 |
| 11 | Stock Conditions 层 | 价格区间检查未实现（stock_pool 数据源缺失） | ✅ 已修复 |

**修复内容**（`src/qing_investment/monitor/rules/__init__.py`）：
- 新增 `stock_pool` 数据源：从 `config.stock_pool.stocks[].entry.primary_zone` 提取介入区间
- 新增 `stock_pool` pre_condition 加载：`sector_diverged` / `market_actionable` / `no_consecutive_limit_up`
- 新增 pre_condition 代码拦截：连续涨停中的标的即使 4/6 条件满足也会被拦截
- 补充逻辑：stock_pool 数据已覆盖但 watchlist 也有同类标的时，自动补充 pre_condition 字段

> ~~#12 Neo4j~~ — **误报**。Neo4j 正常（895 claims），密码 `qingneo4j`，MCP 工具可用。此前用了错误密码 `neo4jneo4j` 导致假阳性。

---

## 执行顺序

```
Phase 1（今天）
  ├── #1  对齐 current_stage 值
  └── #2  修复数据路径

Phase 2（本周）
  ├── #3  改 skill 定位 → claims 下游消费者
  ├── #4  补充 mcp 工具引用
  ├── #5  补全级联更新步骤
  ├── #6  更新方向数量
  └── #7  加 watchlist 并行说明

Phase 3（可延后）
  ├── #8  清单加具体命令
  ├── #9  cron 联动说明
  └── #10-11  代码层 P1
```

---

## 验收标准

- [ ] MLCC、商业航天能通过 SectorGate
- [ ] skill 数据路径指向正确位置
- [ ] skill 引用 mcp 工具作为输入源
- [ ] Config 变更纪律包含完整级联链路
