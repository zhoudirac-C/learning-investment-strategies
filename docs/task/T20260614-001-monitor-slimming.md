# Task: 监控引擎瘦身 — 子模块实现迁移

> 任务ID: T20260614-001
> 优先级: P0 🔴
> 状态: 待执行
> 创建: 2026-06-14
> 负责人: 待分配

---

## 一、任务背景

**触发**: 第十次瘦身完成后，检查发现 stock_monitor.py 中 83 个函数全部改为委托包装，但 71 个函数的底层实现在 monitor/ 子模块中缺失。

**风险**: 当前代码运行时必崩（AttributeError）。

---

## 二、现状数据

| 指标 | 数值 |
|------|------|
| stock_monitor.py 行数 | 974 行（原始 4,309 行） |
| 委托包装函数 | 83 个 |
| 子模块有真实实现 | 12 个 |
| **子模块缺失实现** | **71 个** |

---

## 三、子任务清单

### Subtask 1: monitor/context（11个函数）
**优先级**: 🔴 P0 | **预估工时**: 2-3h | **依赖**: 无

| 函数 | 说明 | 当前位置 |
|------|------|----------|
| `_string_items` | 字符串列表提取 | stock_monitor.py:41 |
| `format_watchlist_condition_line` | 条件行格式化 | stock_monitor.py:48 |
| `sector_group_rows` | 板块分组 | stock_monitor.py:55 |
| `unique_stock_count` | 去重计数 | stock_monitor.py:62 |
| `parse_price_zone` | 价格区间解析 | stock_monitor.py:209 |
| `_to_float` | 浮点数转换 | stock_monitor.py:216 |
| `_pure_stock_code` | 股票代码提取 | stock_monitor.py:223 |
| `_quotes_by_code` | 行情按代码索引 | stock_monitor.py:230 |
| `_quote_for_stock` | 查找股票行情 | stock_monitor.py:237 |
| `_quotes_by_label` | 行情按标签索引 | stock_monitor.py:244 |
| `_format_zone` | 价格区间格式化 | stock_monitor.py:251 |

**验收标准**:
- [x] 11个函数在 `monitor/context/__init__.py` 中有真实实现
- [x] 处理重复定义（sector_group_rows, _string_items 等已有重复）
- [ ] `python -m py_compile` 通过
- [x] E2E测试通过

---

### Subtask 2: monitor/analysis（12个函数）
**优先级**: 🔴 P0 | **预估工时**: 3-4h | **依赖**: Subtask 1

| 函数 | 说明 | 当前位置 |
|------|------|----------|
| `_compute_vs_ma` | 计算相对MA位置 | stock_monitor.py:560 |
| `_compute_near5d_return` | 近5日涨跌幅 | stock_monitor.py:567 |
| `_compute_volume_ratio` | 量比计算 | stock_monitor.py:574 |
| `_check_entry_zone_distance` | 买入区间检查 | stock_monitor.py:581 |
| `_classify_seat_type` | 席位类型判断 | stock_monitor.py:601 |
| `_classify_top_buy_behavior` | 买一行为判断 | stock_monitor.py:608 |
| `_assess_board_quality` | 封板质量评估 | stock_monitor.py:618 |
| `_fetch_dragon_tiger_data` | 龙虎榜数据获取 | stock_monitor.py:625 |
| `_fetch_daily_dragon_tiger_board` | 全市场龙虎榜 | stock_monitor.py:636 |
| `_filter_dragon_tiger_board` | 龙虎榜过滤 | stock_monitor.py:646 |
| `_parse_net_buy_float` | 净买额解析 | stock_monitor.py:657 |
| `_format_net_buy_str` | 净买额格式化 | stock_monitor.py:664 |

**验收标准**:
- [ ] 12个函数在 `monitor/analysis/__init__.py` 中有真实实现
- [ ] 保留 pandas/akshare 依赖和异常处理
- [x] E2E测试通过

---

### Subtask 3: monitor/rules（7个函数）
**优先级**: 🔴 P0 | **预估工时**: 2-3h | **依赖**: Subtask 2

| 函数 | 说明 | 当前位置 |
|------|------|----------|
| `evaluate_position_alerts` | 持仓规则评估 | stock_monitor.py:263 |
| `evaluate_buy_signal_candidates` | 买入信号候选 | stock_monitor.py:273 |
| `evaluate_buy_signal_alerts` | 买入信号告警 | stock_monitor.py:283 |
| `evaluate_market_alerts` | 市场规则评估 | stock_monitor.py:293 |
| `compute_sector_strength` | 板块强度计算 | stock_monitor.py:305 |
| `_aggregate_sector_strength` | 板块强度聚合 | stock_monitor.py:316 |
| `evaluate_sector_rotation_alerts` | 板块轮动告警 | stock_monitor.py:326 |

**验收标准**:
- [ ] 7个函数在 `monitor/rules/__init__.py` 中有真实实现
- [ ] 集成到 RuleEngine 类或作为独立函数
- [x] E2E测试通过

---

### Subtask 4: monitor/output（5个函数）
**优先级**: 🟡 P1 | **预估工时**: 2h | **依赖**: Subtask 3

| 函数 | 说明 | 当前位置 |
|------|------|----------|
| `alert_fingerprint` | 告警指纹生成 | stock_monitor.py:365 |
| `load_monitor_state` | 状态加载 | stock_monitor.py:372 |
| `save_monitor_state` | 状态保存 | stock_monitor.py:382 |
| `format_alert_decision_log` | 决策日志格式化 | stock_monitor.py:417 |
| `update_sector_signal_counts` | 板块信号计数 | stock_monitor.py:434 |
| `update_market_state` | 市场状态更新 | stock_monitor.py:445 |

**验收标准**:
- [ ] 6个函数在 `monitor/output/__init__.py` 中有真实实现
- [ ] 与现有 AlertFormatter / AlertHistory 类兼容
- [x] E2E测试通过

---

### Subtask 5: monitor/scheduler（28个函数）
**优先级**: 🟡 P1 | **预估工时**: 4-5h | **依赖**: Subtask 4

| 函数 | 说明 | 当前位置 |
|------|------|----------|
| `_summary_file_path` | 摘要文件路径 | stock_monitor.py:671 |
| `_build_yesterday_summary` | 昨日摘要构建 | stock_monitor.py:683 |
| `_save_yesterday_summary` | 摘要保存 | stock_monitor.py:693 |
| `_update_summary_tomorrow_scenarios` | 场景更新 | stock_monitor.py:703 |
| `_load_yesterday_summary` | 摘要加载 | stock_monitor.py:712 |
| `_auction_cache_path` | 缓存路径 | stock_monitor.py:722 |
| `_load_auction_cache` | 缓存加载 | stock_monitor.py:732 |
| `_save_auction_cache` | 缓存保存 | stock_monitor.py:743 |
| `_update_auction_cache` | 缓存更新 | stock_monitor.py:754 |
| `_compute_auction_volume_ratio` | 竞价量比 | stock_monitor.py:764 |
| `_compute_auction_vs_yesterday_volume` | 竞价量对比 | stock_monitor.py:774 |
| `_auction_snapshot` | 竞价快照 | stock_monitor.py:785 |
| `_extract_auction_snapshot_for_context` | 快照提取 | stock_monitor.py:794 |
| `_build_sector_tiers` | 板块分层 | stock_monitor.py:804 |
| `_agent_context_data` | Agent数据 | stock_monitor.py:815 |
| `format_agent_analysis_context` | Agent context格式化 | stock_monitor.py:824 |
| `format_agent_json_context` | JSON context格式化 | stock_monitor.py:833 |
| `_state_date` | 日期提取 | stock_monitor.py:842 |
| `summarize_daily_review` | 每日复盘 | stock_monitor.py:853 |
| `_append_review_entries` | 复盘条目追加 | stock_monitor.py:863 |
| `format_daily_review_context` | 复盘context格式化 | stock_monitor.py:872 |
| `run_tick` | 执行tick | stock_monitor.py:944 |
| `build_parser` | 参数解析器 | stock_monitor.py:955 |
| `main` | 主入口 | stock_monitor.py:962 |

**验收标准**:
- [ ] 24个函数在 `monitor/scheduler/__init__.py` 中有真实实现
- [x] 处理重复定义（已有11个函数重复）
- [ ] 删除 stock_monitor.py 中重复的 main 函数
- [x] E2E测试通过

---

## 四、执行顺序

```
Subtask 1 (context) → Subtask 2 (analysis) → Subtask 3 (rules) → Subtask 4 (output) → Subtask 5 (scheduler)
```

**总工时**: 13-17 小时（2-3 个工作日）

---

## 五、验收标准（整体）

- [ ] stock_monitor.py 中 83 个委托包装函数全部可正常调用
- [ ] 无 `AttributeError` / `ImportError`
- [ ] `python -m pytest monitor/tests/test_e2e.py -v` 全部通过
- [ ] stock_monitor.py 行数 < 200（仅保留导入和委托包装）
- [ ] 所有子模块 `__init__.py` 语法正确

---

## 六、风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| 函数依赖循环 | 中 | 高 | 按 Subtask 顺序执行，context 优先 |
| 重复定义冲突 | 高 | 中 | 仔细比对，保留最新版本 |
| 异常处理丢失 | 中 | 高 | 迁移时保留完整 try/except |
| 测试覆盖不足 | 中 | 中 | 每 Subtask 完成后运行 E2E |

---

## 七、相关文档

| 文档 | 路径 |
|------|------|
| 架构优化方案 v1.1 | `docs/design/architecture-optimization-plan.md` |
| 监控技术设计 | `docs/hermes-stock-monitor-technical-design.md` |
| E2E测试 | `monitor/tests/test_e2e.py` |

---

*任务版本: v1.0*
*创建: 2026-06-14*
*状态: 待执行*
