# 设计文档实现差距审计（2026-06-10）

> 审计目标：`docs/config-cron-architecture-review.md` 中的设计 vs 代码实际实现
> 审计方法：文件系统检查 + 代码确认，不依赖文档描述

## 总体结论

设计的 **~80% 已完成落地**。Phase 1（Prompt 改造）+ Phase 2（Context Builder）+ Phase 3（Cron/状态机）基本完成。Phase 4（全链路自动化）有显著差距。

## Phase 核查

### Phase 1: Prompt 层改造 ✅ 全部完成

| 任务 | 状态 | 实况 |
|------|------|------|
| 1.1 market_analyst prompt 重写 | ✅ | 12.7KB，含赔率框架(10处)、daily_state(3处) |
| 1.2 cron prompt 差异化 | ✅ | 9个独立 cron_*.txt（38-54行/个），按时间节点加载 |
| 1.3 trader_mindset.txt | ✅ | 89行/4.7KB，含"赔率思维"等核心人格 |
| 1.4 新旧 prompt 自测 | 📌 | 未核实 |

### Phase 2: Context Builder ✅ 全部完成（已修复）

| 任务 | 状态 | 实况 |
|------|------|------|
| 2.1 context_builder.py | ✅ | 429行，Neo4j+Qdrant+浓度控制+Pattern排序 |
| 2.2 集成到 retrieve_knowledge | ✅ | nodes.py 1014-1096行 |
| 2.3 注入到分析流程 | ✅ | 走 Qing-Agent 工作流（非 cron prompt） |

> ⚠️ **关键发现**：Context Builder 此前因 `neotime.Date` vs str 类型崩溃被 `except: pass` 吞掉，从未真正工作。2026-06-10 修复。

### Phase 3: Cron + 状态机 ⚠️ 大部分完成

| 任务 | 状态 | 实况 |
|------|------|------|
| 3.1 daily_state 读写 | ✅ | daily_state.json 存在(5KB)，结构完整 |
| 3.2 LLM cron 差异化 | ✅ | 9个 cron job 全部启用，独立 prompt |
| 3.3 add_zone 触发 | ⚠️ | stock_monitor.py 已实现 `evaluate_position_alerts()`，但消息格式未按文档示例格式化 |
| 3.4 删除冗余 cron | ❌→已纠正 | v2.0 已改为「不减少，差异化」 |

### Phase 4: 观察池热度 + Claims 自动化 ⚠️ 部分完成

| 任务 | 状态 | 实况 |
|------|------|------|
| 4.1 热度分计算 | ✅ | calc_hot_scores.py(64行) + tools/hot_score.py，cron 每天09:00 |
| 4.2 Claims→Entry 桥接 | ⚠️ | sync_claims_to_config.py(84行)存在，但 entry_points 仅 3/12 有完整字段 |
| 4.3 全链路自动化 | ❌ | 新 claims→自动 discover→Neo4j→Qdrant→Agent 重启 未实现 |

## §7.2 修改清单核查

### 新增文件 ✅ 全部存在

| 文件 | 行数 | 实况 |
|------|------|------|
| trader_mindset.txt | 89 | ✅ 真实人格内容 |
| sync_claims_to_config.py | 84 | ✅ 存在，但桥接不完整 |
| sync_daily_state.py | 250 | ✅ cron 已注册 |
| qing_stock_monitor_poll.py | 49 | ✅ cron 已注册 |
| backfill_linked_claims.py | 76 | ✅ 已回填 23/180 只(13%) |

### Config 更新 ⚠️ 部分完成

| 项 | 状态 | 实况 |
|----|------|------|
| position_rules 7个 | ✅ | 对应7大机会模式 |
| linked_claims 回填 | ⚠️ | 23/180(13%)，覆盖率低 |
| entry_points 增强字段 | ⚠️ | 仅 3/12 有 status/odds_analysis/claim_basis |

## 未实现清单

### P0 真正缺失

1. **全链路自动化管线**：新 claims → 自动 discover → Neo4j → Qdrant → Agent 重启
2. **entry_points 9/12 缺增强字段**：无 status/odds_analysis/claim_basis

### P1 部分完成需迭代

1. **linked_claims 仅 13%**：Context Builder 依赖精准检索
2. **sync_claims_to_config 桥接不完整**：代码存在但 entry_points 几乎未更新
3. **条件驱动轮询 add_zone 消息格式**：纯文本，未按文档示例格式化

### P2 文档过期

1. §7.3 遗留问题#2 写"无 fallback"——实际已有持久化 fallback
2. §7.2 新增文件缺少 daily_state.py/hot_score.py——实际已存在
