# Qing-Agent 监控引擎瘦身实施路线图

> 日期：2026-06-14
> 触发：第十次瘦身完成 + 子模块实现缺失检查
> 目标：完成 stock_monitor.py 到 monitor/ 子模块的完整迁移，消除运行时崩溃风险
> 状态：实施文档，待执行

---

## 一、现状诊断

### 1.1 当前状态

| 指标 | 数值 |
|------|------|
| stock_monitor.py 行数 | 974 行（原始 4,309 行） |
| 累计减少 | -3,335 行 (-77.4%) |
| 函数总数 | 83 个 |
| 委托包装函数 | 83 个（100%） |
| **子模块有真实实现** | **12 个** |
| **子模块缺失实现** | **71 个** |

### 1.2 核心问题

**⚠️ 运行时必崩**：stock_monitor.py 中 71 个函数委托到了 monitor/ 子模块，但子模块中不存在对应实现。

当前调用链：
```
stock_monitor.py:evaluate_position_alerts()
  → 委托到 monitor.rules:evaluate_position_alerts()
  → ❌ 函数不存在 → AttributeError
```

### 1.3 缺失实现分布

| 子模块 | 缺失函数数 | 已有函数数 | 状态 |
|--------|----------|----------|------|
| monitor/rules | 7 | 1 | 🔴 严重 |
| monitor/output | 5 | 3 | 🔴 严重 |
| monitor/scheduler | 28 | 11 | 🔴 严重 |
| monitor/analysis | 12 | 0 | 🔴 最严重 |
| monitor/context | 11 | 0 | 🔴 最严重 |
| monitor/fetchers | 2 | 2 | ✅ 完整 |

---

## 二、实施路线图

### 2.1 五批次迁移计划

| 批次 | 目标模块 | 函数数 | 优先级 | 预估工时 | 依赖 |
|------|---------|--------|--------|----------|------|
| **Batch 1** | monitor/context | 11 | 🔴 P0 | 2-3h | 无 |
| **Batch 2** | monitor/analysis | 12 | 🔴 P0 | 3-4h | Batch 1 |
| **Batch 3** | monitor/rules | 7 | 🔴 P0 | 2-3h | Batch 2 |
| **Batch 4** | monitor/output | 5 | 🟡 P1 | 2h | Batch 3 |
| **Batch 5** | monitor/scheduler | 28 | 🟡 P1 | 4-5h | Batch 4 |

**总工时**：约 13-17 小时（2-3 个工作日）

---

## 三、Batch 1：monitor/context（11个函数）

### 3.1 目标函数

| 函数 | 行数 | 说明 | 当前位置 |
|------|------|------|----------|
| `_string_items` | ~8 | 字符串列表提取 | stock_monitor.py:41 |
| `format_watchlist_condition_line` | ~15 | 条件行格式化 | stock_monitor.py:48 |
| `sector_group_rows` | ~20 | 板块分组 | stock_monitor.py:55 |
| `unique_stock_count` | ~12 | 去重计数 | stock_monitor.py:62 |
| `parse_price_zone` | ~24 | 价格区间解析 | stock_monitor.py:209 |
| `_to_float` | ~12 | 浮点数转换 | stock_monitor.py:216 |
| `_pure_stock_code` | ~3 | 股票代码提取 | stock_monitor.py:223 |
| `_quotes_by_code` | ~8 | 行情按代码索引 | stock_monitor.py:230 |
| `_quote_for_stock` | ~4 | 查找股票行情 | stock_monitor.py:237 |
| `_quotes_by_label` | ~7 | 行情按标签索引 | stock_monitor.py:244 |
| `_format_zone` | ~4 | 价格区间格式化 | stock_monitor.py:251 |

### 3.2 实施步骤

1. **从 stock_monitor.py 提取原实现** → 迁移到 `monitor/context/__init__.py`
2. **处理重复定义** — `sector_group_rows`, `_string_items`, `format_watchlist_condition_line`, `unique_stock_count` 在 context 中已有重复定义，需合并
3. **验证导入路径** — 确保 `qing_investment.monitor.context` 正确导出所有函数
4. **运行测试** — `python -m pytest monitor/tests/test_e2e.py -v`

### 3.3 注意事项

- `context` 模块中已有部分函数的重复定义（第77行和第235行），需去重
- 这些函数是基础工具函数，被其他模块依赖，需优先完成

---

## 四、Batch 2：monitor/analysis（12个函数）

### 4.1 目标函数

| 函数 | 行数 | 说明 | 当前位置 |
|------|------|------|----------|
| `_compute_vs_ma` | ~15 | 计算相对MA位置 | stock_monitor.py:560 |
| `_compute_near5d_return` | ~15 | 近5日涨跌幅 | stock_monitor.py:567 |
| `_compute_volume_ratio` | ~15 | 量比计算 | stock_monitor.py:574 |
| `_check_entry_zone_distance` | ~30 | 买入区间检查 | stock_monitor.py:581 |
| `_classify_seat_type` | ~20 | 席位类型判断 | stock_monitor.py:601 |
| `_classify_top_buy_behavior` | ~40 | 买一行为判断 | stock_monitor.py:608 |
| `_assess_board_quality` | ~30 | 封板质量评估 | stock_monitor.py:618 |
| `_fetch_dragon_tiger_data` | ~50 | 龙虎榜数据获取 | stock_monitor.py:625 |
| `_fetch_daily_dragon_tiger_board` | ~40 | 全市场龙虎榜 | stock_monitor.py:636 |
| `_filter_dragon_tiger_board` | ~60 | 龙虎榜过滤 | stock_monitor.py:646 |
| `_parse_net_buy_float` | ~20 | 净买额解析 | stock_monitor.py:657 |
| `_format_net_buy_str` | ~20 | 净买额格式化 | stock_monitor.py:664 |

### 4.2 实施步骤

1. **从 stock_monitor.py 提取原实现** → 迁移到 `monitor/analysis/__init__.py`
2. **处理 pandas 依赖** — 部分函数使用 `pd.DataFrame`，需确保导入
3. **处理 akshare 依赖** — 龙虎榜相关函数依赖 akshare，需检查异常处理
4. **验证** — 运行 E2E 测试

### 4.3 注意事项

- 这些函数涉及数据计算和外部 API 调用，需保留完整的异常处理逻辑
- `_fetch_dragon_tiger_data` 和 `_fetch_daily_dragon_tiger_board` 有超时参数，需保留

---

## 五、Batch 3：monitor/rules（7个函数）

### 5.1 目标函数

| 函数 | 行数 | 说明 | 当前位置 |
|------|------|------|----------|
| `evaluate_position_alerts` | ~80 | 持仓规则评估 | stock_monitor.py:263 |
| `evaluate_buy_signal_candidates` | ~60 | 买入信号候选 | stock_monitor.py:273 |
| `evaluate_buy_signal_alerts` | ~40 | 买入信号告警 | stock_monitor.py:283 |
| `evaluate_market_alerts` | ~40 | 市场规则评估 | stock_monitor.py:293 |
| `compute_sector_strength` | ~50 | 板块强度计算 | stock_monitor.py:305 |
| `_aggregate_sector_strength` | ~30 | 板块强度聚合 | stock_monitor.py:316 |
| `evaluate_sector_rotation_alerts` | ~40 | 板块轮动告警 | stock_monitor.py:326 |

### 5.2 实施步骤

1. **从 stock_monitor.py 提取原实现** → 迁移到 `monitor/rules/__init__.py`
2. **集成到 RuleEngine 类** — 考虑将这些函数作为 `RuleEngine` 类的方法或独立函数
3. **处理依赖** — 这些函数依赖 `RuleAlert`, `MonitorConfig` 等类型
4. **验证** — 运行 E2E 测试

### 5.3 注意事项

- `evaluate_monitor_alerts` 已在 rules 中有实现（第789行），但其他7个函数缺失
- 这些函数是核心规则引擎，需确保逻辑完整迁移

---

## 六、Batch 4：monitor/output（5个函数）

### 6.1 目标函数

| 函数 | 行数 | 说明 | 当前位置 |
|------|------|------|----------|
| `alert_fingerprint` | ~10 | 告警指纹生成 | stock_monitor.py:365 |
| `load_monitor_state` | ~15 | 状态加载 | stock_monitor.py:372 |
| `save_monitor_state` | ~10 | 状态保存 | stock_monitor.py:382 |
| `format_alert_decision_log` | ~20 | 决策日志格式化 | stock_monitor.py:417 |
| `update_sector_signal_counts` | ~20 | 板块信号计数 | stock_monitor.py:434 |
| `update_market_state` | ~40 | 市场状态更新 | stock_monitor.py:445 |

### 6.2 实施步骤

1. **从 stock_monitor.py 提取原实现** → 迁移到 `monitor/output/__init__.py`
2. **集成到现有类** — `load_monitor_state`/`save_monitor_state` 可集成到 `AlertHistory` 类
3. **处理依赖** — `update_market_state` 依赖 `_quotes_by_code` 等函数（已在 context 中）
4. **验证** — 运行 E2E 测试

### 6.3 注意事项

- `filter_new_alerts`, `record_emitted_alerts`, `format_alerts_message` 已在 output 中有实现
- `load_monitor_state`/`save_monitor_state` 在 scheduler 中也有定义，需统一

---

## 七、Batch 5：monitor/scheduler（28个函数）

### 7.1 目标函数

| 函数 | 行数 | 说明 | 当前位置 |
|------|------|------|----------|
| `_summary_file_path` | ~5 | 摘要文件路径 | stock_monitor.py:671 |
| `_build_yesterday_summary` | ~80 | 昨日摘要构建 | stock_monitor.py:683 |
| `_save_yesterday_summary` | ~20 | 摘要保存 | stock_monitor.py:693 |
| `_update_summary_tomorrow_scenarios` | ~30 | 场景更新 | stock_monitor.py:703 |
| `_load_yesterday_summary` | ~20 | 摘要加载 | stock_monitor.py:712 |
| `_auction_cache_path` | ~10 | 缓存路径 | stock_monitor.py:722 |
| `_load_auction_cache` | ~20 | 缓存加载 | stock_monitor.py:732 |
| `_save_auction_cache` | ~20 | 缓存保存 | stock_monitor.py:743 |
| `_update_auction_cache` | ~20 | 缓存更新 | stock_monitor.py:754 |
| `_compute_auction_volume_ratio` | ~20 | 竞价量比 | stock_monitor.py:764 |
| `_compute_auction_vs_yesterday_volume` | ~20 | 竞价量对比 | stock_monitor.py:774 |
| `_auction_snapshot` | ~20 | 竞价快照 | stock_monitor.py:785 |
| `_extract_auction_snapshot_for_context` | ~15 | 快照提取 | stock_monitor.py:794 |
| `_build_sector_tiers` | ~20 | 板块分层 | stock_monitor.py:804 |
| `_agent_context_data` | ~30 | Agent数据 | stock_monitor.py:815 |
| `format_agent_analysis_context` | ~30 | Agent context格式化 | stock_monitor.py:824 |
| `format_agent_json_context` | ~20 | JSON context格式化 | stock_monitor.py:833 |
| `_state_date` | ~15 | 日期提取 | stock_monitor.py:842 |
| `summarize_daily_review` | ~30 | 每日复盘 | stock_monitor.py:853 |
| `_append_review_entries` | ~20 | 复盘条目追加 | stock_monitor.py:863 |
| `format_daily_review_context` | ~20 | 复盘context格式化 | stock_monitor.py:872 |
| `run_tick` | ~50 | 执行tick | stock_monitor.py:944 |
| `build_parser` | ~30 | 参数解析器 | stock_monitor.py:955 |
| `main` | ~20 | 主入口 | stock_monitor.py:962 |

### 7.2 实施步骤

1. **从 stock_monitor.py 提取原实现** → 迁移到 `monitor/scheduler/__init__.py`
2. **处理重复定义** — `agent_analysis_schedule_rows`, `_hhmm`, `_agent_history`, `_agent_dedupe_key_for_schedule`, `find_agent_analysis_trigger`, `find_any_agent_analysis_trigger`, `record_agent_analysis_trigger`, `is_scheduled_agent_analysis_time` 在 scheduler 中已有重复定义，需合并
3. **处理 main 函数** — `main` 和 `run_tick` 是入口函数，需确保正确委托
4. **验证** — 运行 E2E 测试

### 7.3 注意事项

- scheduler 模块中已有大量重复定义，需仔细合并避免冲突
- `main` 函数在 stock_monitor.py 中有重复定义（第962行和第969行），需删除一个

---

## 八、验证清单

### 8.1 每批次完成后验证

- [ ] 语法检查：`python -m py_compile stock_monitor.py`
- [ ] 导入检查：`python -c "from qing_investment.stock_monitor import *"`
- [ ] E2E测试：`python -m pytest monitor/tests/test_e2e.py -v`
- [ ] 行数统计：`wc -l stock_monitor.py`

### 8.2 全部完成后验证

- [ ] 所有83个函数委托包装可正常调用
- [ ] 无 `AttributeError` 或 `ImportError`
- [ ] E2E测试全部通过
- [ ] stock_monitor.py 行数 < 200（目标：仅保留导入和委托包装）

---

## 九、风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| 函数依赖循环 | 中 | 高 | 提前梳理依赖图，按批次顺序执行 |
| 重复定义冲突 | 高 | 中 | 仔细比对现有实现，保留最新版本 |
| 异常处理丢失 | 中 | 高 | 迁移时保留完整的 try/except 块 |
| 类型注解丢失 | 低 | 低 | 迁移时保留类型注解 |
| 测试覆盖不足 | 中 | 中 | 每批次完成后运行 E2E 测试 |

---

## 十、相关文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 架构优化方案 v1.1 | `docs/design/architecture-optimization-plan.md` | 整体设计方向 |
| 监控技术设计 | `docs/hermes-stock-monitor-technical-design.md` | 监控层现有设计 |
| 技术设计 | `docs/qing-agent-technical-design.md` | 现有架构完整描述 |
| E2E测试 | `monitor/tests/test_e2e.py` | 端到端测试 |

---

*文档版本: v1.0*
*设计: 2026-06-14*
*状态: 实施文档，基于第十次瘦身检查结果*
