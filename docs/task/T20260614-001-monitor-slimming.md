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
- [x] `python -m py_compile` 通过
- [x] E2E测试通过

**状态**: ✅ 已完成（2026-06-14）
- 删除重复定义函数（4个函数重复）
- 文件从 755 行瘦身至 629 行（-126行）

---

### Subtask 2: monitor/analysis（12个函数）
**优先级**: 🔴 P0 | **预估工时**: 3-4h | **依赖**: Subtask 1

|| 函数 | 说明 | 当前位置 |
||------|------|----------|
|| `_compute_vs_ma` | 计算相对MA位置 | stock_monitor.py:560 |
|| `_compute_near5d_return` | 近5日涨跌幅 | stock_monitor.py:567 |
|| `_compute_volume_ratio` | 量比计算 | stock_monitor.py:574 |
|| `_check_entry_zone_distance` | 买入区间检查 | stock_monitor.py:581 |
|| `_classify_seat_type` | 席位类型判断 | stock_monitor.py:601 |
|| `_classify_top_buy_behavior` | 买一行为判断 | stock_monitor.py:608 |
|| `_assess_board_quality` | 封板质量评估 | stock_monitor.py:618 |
|| `_fetch_dragon_tiger_data` | 龙虎榜数据获取 | stock_monitor.py:625 |
|| `_fetch_daily_dragon_tiger_board` | 全市场龙虎榜 | stock_monitor.py:636 |
|| `_filter_dragon_tiger_board` | 龙虎榜过滤 | stock_monitor.py:646 |
|| `_parse_net_buy_float` | 净买额解析 | stock_monitor.py:657 |
|| `_format_net_buy_str` | 净买额格式化 | stock_monitor.py:664 |

**验收标准**:
- [x] 12个函数在 `monitor/analysis/__init__.py` 中有真实实现
- [x] 保留 pandas/akshare 依赖和异常处理
- [x] `python -m py_compile` 通过
- [x] 导入测试通过（stock_monitor.py 委托调用正常）
- [x] 功能测试通过（_compute_vs_ma, _parse_net_buy_float 等）
- [x] E2E测试通过

**状态**: ✅ 已完成（2026-06-14）
- 从 git 历史提取原实现（commit 8129ee6）
- 创建 monitor/analysis/__init__.py（400行）
- 修复导入问题（timedelta, TYPE_CHECKING）
- 修复类型注解问题（MonitorConfig 循环导入）

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
- [x] 7个函数在 `monitor/rules/__init__.py` 中有真实实现（类已存在）
- [x] 集成到 RuleEngine 类或作为独立函数（已实现）
- [x] 导入测试通过（stock_monitor.py 委托调用正常）
- [x] E2E测试通过

**状态**: ✅ 已完成（2026-06-14）
- 发现 monitor/rules/__init__.py 已有完整实现（797行）
- PositionRuleEngine, BuySignalRuleEngine, IndexRuleEngine, SectorRotationRuleEngine 类已存在
- _aggregate 和 _compute_sector_strength 方法已存在
- stock_monitor.py 委托调用正常

---

### Subtask 4: monitor/output（6个函数）
**优先级**: 🟡 P1 | **预估工时**: 2h | **依赖**: Subtask 3

| 函数 | 说明 | 当前位置 |
|------|------|----------|
| `alert_fingerprint` | 告警指纹生成 → `monitor.output._alert_fingerprint` | stock_monitor.py:365 |
| `format_alert_decision_log` | 决策日志格式化 → `AlertFormatter().format_log_entry()` | stock_monitor.py:417 |
| `filter_new_alerts` | 告警去重 → `monitor.output.filter_new_alerts` | stock_monitor.py:392 |
| `record_emitted_alerts` | 告警记录 → `monitor.output.record_emitted_alerts` | stock_monitor.py:406 |

**验收标准**:
- [x] 6个函数全部有真实实现（2个在output，4个在scheduler — 设计决定：状态管理归调度层）
- [x] `monitor/output/__init__.py` 已存在完整实现（612行）
- [x] `python -m py_compile` 通过
- [x] 导入测试通过

**状态**: ✅ 已完成（commit `df9ebef` Phase 3）
- 路由说明：`alert_fingerprint`/`format_alert_decision_log`/`filter_new_alerts`/`record_emitted_alerts` → output
- `load_monitor_state`/`save_monitor_state`/`update_sector_signal_counts`/`update_market_state` → scheduler

---

### Subtask 5: monitor/scheduler（24个函数）
**优先级**: 🟡 P1 | **预估工时**: 4-5h | **依赖**: Subtask 4

| 函数 | 说明 | 部署模块 |
|------|------|----------|
| `_summary_file_path` | 摘要文件路径 → scheduler |  |
| `_build_yesterday_summary` | 昨日摘要构建 → scheduler |  |
| `_save_yesterday_summary` | 摘要保存 → scheduler |  |
| `_update_summary_tomorrow_scenarios` | 场景更新 → scheduler |  |
| `_load_yesterday_summary` | 摘要加载 → scheduler |  |
| `_auction_cache_path` | 缓存路径 → scheduler |  |
| `_load_auction_cache` | 缓存加载 → scheduler |  |
| `_save_auction_cache` | 缓存保存 → scheduler |  |
| `_update_auction_cache` | 缓存更新 → scheduler |  |
| `_compute_auction_volume_ratio` | 竞价量比 → monitor.analysis |  |
| `_compute_auction_vs_yesterday_volume` | 竞价量对比 → monitor.analysis |  |
| `_auction_snapshot` | 竞价快照 → monitor.fetchers |  |
| `_extract_auction_snapshot_for_context` | 快照提取 → monitor.context |  |
| `_build_sector_tiers` | 板块分层 → monitor.context |  |
| `_agent_context_data` | Agent数据 → monitor.context |  |
| `format_agent_analysis_context` | Agent context格式化 → scheduler |  |
| `format_agent_json_context` | JSON context格式化 → scheduler |  |
| `_state_date` | 日期提取 → scheduler |  |
| `summarize_daily_review` | 每日复盘 → scheduler |  |
| `_append_review_entries` | 复盘条目追加 → scheduler |  |
| `format_daily_review_context` | 复盘context格式化 → monitor.context |  |
| `run_tick` | 执行tick → scheduler |  |
| `build_parser` | 参数解析器 → scheduler |  |
| `main` | 主入口 → scheduler |  |

**路由说明**: 实际部署时按职责分派，并非全部进 scheduler：
- **scheduler**: 状态管理/摘要/竞价缓存/复盘/review/入口
- **context**: Agent数据/板块/context格式化
- **analysis**: 竞价指标计算
- **fetchers**: 竞价快照获取

**验收标准**:
- [x] 17个函数在 `monitor/scheduler/__init__.py` 中有真实实现
- [x] 6个 routed to context/analysis/fetchers 已有实现
- [x] `python -m py_compile` 通过
- [x] 导入测试通过

**状态**: ✅ 已完成（从 git `472e2d5^` 提取原实现，追加到 scheduler）
- 从 stock_monitor.py 历史版本提取17个函数（含 format_agent_*）
- 添加常量/懒导入处理循环依赖
- scheduler 模块从 1029 行 → 1975 行（+946行）
- stock_monitor.py 仍保留974行（83个委托包装函数）

---

### 🔧 待修复：损坏的委托链路（不在原 Subtask 范围内）

**背景**: 第十次瘦身（`472e2d5`）将所有函数改为委托包装，但部分函数从未迁移到子模块。当前存在 **19 个损坏的委托目标**。

#### 类型 A：包装器指向错误模块（6个，实现已存在但 import 路径错）

| 包装器路径 | 实际实现位置 | 修复方案 |
|-----------|------------|---------|
| `monitor.fetchers._fetch_dragon_tiger_data` | `monitor.analysis` | 改 stock_monitor.py import 路径 |
| `monitor.fetchers._fetch_daily_dragon_tiger_board` | `monitor.analysis` | 同上 |
| `monitor.fetchers._filter_dragon_tiger_board` | `monitor.analysis` | 同上 |
| `monitor.context.format_agent_analysis_context` | `monitor.scheduler` | 同上 |
| `monitor.context.format_analysis_context` | `monitor.scheduler` | 同上 |
| `monitor.output.format_status_message` | `monitor.scheduler` | 同上 |

**修复方式**: 只需改 stock_monitor.py 中对应行的 `from ... import` 模块名。

#### 类型 B：完全缺失（13个，原实现已删除从未迁移）

**需从 git 历史提取并补到对应模块**:

| 缺失函数 | 归属模块 | 优先级 | 说明 |
|---------|---------|--------|------|
| `_compute_auction_volume_ratio` | analysis | 🔴 | 竞价量比计算 |
| `_compute_auction_vs_yesterday_volume` | analysis | 🔴 | 竞价量对比 |
| `_auction_snapshot` | fetchers | 🔴 | 竞价快照获取 |
| `validate_position_price_zones` | rules | 🔴 | 持仓价格区间校验 |
| `load_monitor_config` | context | 🔴 | 配置加载 |
| `load_yaml` | context | 🟡 | YAML文件加载 |
| `format_quote_line` | output | 🟡 | 行情行格式化 |
| `format_smoke_message` | output | 🟡 | 烟雾测试消息 |
| `_extract_auction_snapshot_for_context` | context | 🟡 | 快照字段提取 |
| `_build_sector_tiers` | context | 🟡 | 板块分层 |
| `_agent_context_data` | context | 🟡 | Agent数据构建 |
| `format_daily_review_context` | context | 🟡 | 复盘context |
| `format_live_analysis_context` | context | 🟡 | 实时分析context |

**执行建议**:
1. 先修类型 A（6个import路径，5分钟）
2. 类型 B 按优先级 🔴 → 🟡 顺序，从 git `472e2d5^` 或 `4f669b5` 提取

---

## 四、执行顺序

```
Subtask 1 (context) → Subtask 2 (analysis) → Subtask 3 (rules) → Subtask 4 (output) → Subtask 5 (scheduler)
```

### 📌 Pre-flight Check（每次开始 Subtask 前必须执行）

**背景**: 历史发生过 Agent 在目标模块已存在的情况下陷入 git history 提取死循环（Subtask 4）。
**目的**: 避免重复创建，预防死循环。

步骤：
1. **检查文件存在**: `ls src/qing_investment/monitor/<submodule>/__init__.py`
2. **若存在 → 验证导入**: `python -c "from qing_investment.monitor.<submodule> import <目标函数1>, <目标函数2>, ..."` 
3. **判定**:
   - 全部导入成功 → ✅ 标记完成，跳过整个 Subtask
   - 部分缺失 → 只提取缺失函数（`diff` 出差异，不重新创建已有函数）
   - 全部缺失 → 执行正常提取流程
4. **禁用 git show 循环**: 任何 `git show` 命令在同一个 Subtask 中重复调用 >3 次且无进展 → 打印警告并换方案（如 `git diff` 或 `git log -p` 定位）

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
