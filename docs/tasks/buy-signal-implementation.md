# 买入信号检测系统 — 实施任务清单

> 依据：`docs/design/buy-signal-detection-system.md` v1.2
> 原则：完成一个打钩一个，再推进下一个。云端任务标记为 [云端]，本地完成后暂停等待云端对接。

---

## Phase 0: K线缓存基础设施

### 0.1 创建 `src/qing_investment/kline_cache.py`
- [x] SQLite 封装：连接管理（WAL 模式、只读模式）
- [x] `init_db()`：创建 `stocks_kline` 表 + 索引 + `kline_meta` 表
- [x] `save_klines(code, klines)`：覆盖写入单只股票 K线
- [x] `get_klines(code, days)`：读取最近 N 日 K线
- [x] `get_ma(code, days)`：计算移动平均线
- [x] `is_cache_ready(date)` / `mark_cache_ready(date)`：预拉取完成标记
- [x] 单元测试：写入 → 读取 → 查询 MA → 验证数据一致性（9/9 通过）

### 0.2 创建 `scripts/pre_fetch_klines.py`
- [x] 读取 watchlist.yaml + positions.yaml → 合并去重代码列表
- [x] 时区校验：强制 `Asia/Shanghai`，非 06:00-09:15 窗口 skip
- [x] 分批次拉取日K（BATCH_SIZE=5，间隔 3s，单只 0.5s）
- [x] 失败重试：指数退避（5s/10s），最多 3 次
- [x] 写入 SQLite + 标记完成
- [x] 返回码：失败率 ≤20% 返回 0，>20% 返回 1（cron 可告警）
- [x] 单元测试：mock API 验证全流程（5/5 通过）

### 0.3 改造 `src/qing_investment/agent/tools/stock_data.py`
- [x] `fetch_stock_kline()` 优先查 SQLite → miss 则调 API → 写入 SQLite
- [x] 保持向后兼容：不影响现有调用方
- [x] `get_klines()` 返回字段名兼容 API 格式（`trade_date` → `date`）
- [x] 本地测试：14/14 通过

### 0.4 Cron wrapper 与集成验收
- [x] 创建 `scripts/hermes_pre_fetch_klines.py`（Hermes cron 入口，venv/uv 双 fallback）
- [x] SQLite 初始化、读写、MA 计算、缓存标记全部通过单元测试验证（14/14）
- [x] pre_fetch 失败后 fallback 到 API 的逻辑已在 `fetch_stock_kline()` 中实现
- [x] 全部本地测试通过（83/83）

---

## Phase 1: Agent 输出格式改造

### 1.1 修改 `stock_analyst.txt`
- [x] 在 `stock_analyst.txt` 中新增【买入确认模式】分支（当 trigger.kind == "buy_signal_candidate" 时激活）
- [x] 嵌入"深度确认 checklist"（7 项强制验证：价格区间、板块轮动、排名前30%、缩量、均线、赔率>=2:1、非加速段）
- [x] 嵌入"赔率计算强制要求"（>= 2:1，否则 🔴不买）
- [x] 二值化输出模板：🟢买入确认 / 🔴不买入 / 📋条件单待触发
- [x] JSON 输出格式新增 `buy_decision`、`confidence_score`、`checklist_result`、`key_risk`、`next_check_time`

### 1.2 观察池标签修正
- [x] `skills/qing-stock-analysis/SKILL.md` 已明确禁止「✅ 可买」，改用「📋 条件单待触发」（陷阱 26）
- [x] `skills/qing-stock-monitor-update/SKILL.md` 陷阱 24 已完成整改说明

---

## Phase 2: poll 候选筛选（读本地 K线）

### 2.1 实现 `BuySignalCandidate` dataclass
- [x] 字段：stock_code / stock_name / price / is_candidate / matched_conditions / entry_zone / stop_loss / claim_basis / odds_analysis
- [x] 综合判定：满足 >=4/6 条件 → 候选

### 2.2 实现 `evaluate_buy_signal_candidates()`
- [x] 读本地 SQLite K线计算缩量和均线
- [x] 读实时行情计算价格和涨跌幅
- [x] 读 entry_points / add_zone / watchlist.buy_setup 配置
- [x] 输出候选列表

### 2.3 集成到 `evaluate_monitor_alerts()`
- [x] `evaluate_buy_signal_alerts()` 将候选转换为 RuleAlert（action="机会候选"）
- [x] `evaluate_monitor_alerts()` 追加 buy_signal alert 到总 alert 列表
- [ ] 候选写入 `daily_state.json` → `active_opportunities`（待 Phase 4）

### 2.4 单元测试
- [ ] 模拟 K线数据 → 验证缩量/均线计算正确性
- [ ] 模拟实时行情 → 验证价格区间/涨跌幅判断正确性
- [x] 现有 stock_monitor 测试全部通过（83/83）

---

## Phase 2.5: 历史回测验证（可选但强烈推荐）

### 2.5.1 创建 `scripts/backtest_buy_signals.py`
- [ ] 用 akshare 获取 2024-2025 年历史日K
- [ ] 对 watchlist 标的运行候选筛选逻辑
- [ ] 统计信号后 1/3/5/10 日收益率分布

### 2.5.2 回测报告
- [ ] 胜率、平均收益、最大回撤
- [ ] 校准 `odds_analysis` 参数

---

## Phase 3: Agent 单票分析链路

### 3.1 改造 `hermes_stock_monitor_agent.py`
- [x] `find_agent_analysis_trigger()` 检测买入候选 alert → 生成 `kind="buy_signal_candidate"` trigger
- [x] `find_any_agent_analysis_trigger()` 同步支持买入候选检测
- [x] `_agent_context_data()` 动态设置 `analysis_type="stock"` + `stock_code` + `buy_signal_candidates` 上下文
- [x] `hermes_stock_monitor_agent.py` POST 时读取 `analysis_type` / `stock_code` / `buy_signal_candidates` 注入 payload
- [x] `TriggerRequest` schema 新增 `buy_signal_candidates` 字段
- [x] `main.py` `/analyze/trigger` endpoint 将候选数据传入 Agent state

### 3.2 改造 `stock_analyst` 节点
- [x] `stock_analyst.txt` 已新增买入确认模式分支（trigger.kind == "buy_signal_candidate"）
- [x] `nodes.py`：`stock_analyst()` 检测 trigger.kind → 注入 `buy_signal_candidate` 详情到 context
- [x] 买入确认模式输出二值化结论（🟢/🔴/📋）+ checklist_result + confidence_score

### 3.3 端到端测试
- [ ] 手动标记候选 → 触发 stock 分析 → 观察微信推送

---

## Phase 4: 全自动闭环

### 4.1 状态流转自动化
- [x] poll 候选自动写入 daily_state（`tick()` 中调用 `sync_buy_candidates()`）
- [x] cron 自动检测触发（`find_agent_analysis_trigger()` + `find_any_agent_analysis_trigger()`）

### 4.2 去重逻辑
- [x] 价格分桶 + 4 小时窗口实现（`should_trigger_agent_for_candidate()`，桶大小 1%，冷却 4h）

### 4.3 反向流转
- [x] 价格跌破 zone / 板块走弱 → 候选失效（`sync_buy_candidates()` 自动标记不在列表中的为"失效"）

### 4.4 异常处理
- [x] K线拉取失败 → 降级为 API fallback（`fetch_stock_kline()` 中实现）
- [x] daily_state 同步失败 → 不影响主流程（`tick()` 中 try/except 包裹）

### 4.5 每日清理
- [x] 收盘后自动归档 daily_state（`archive_daily_state()` 已存在，跨天自动重建）

---

## [云端] 待云端对接的任务

> 以下任务需要云端 Hermes 环境配合，本地完成后标记为 [云端待部署]，等待云端识别实现。

- [ ] **[云端]** Hermes cron 新增 `pre_fetch_klines` 任务（06:30，周一到周五）
- [ ] **[云端]** 确认云端服务器时区为 `Asia/Shanghai`，或 cron 配置显式指定 timezone
- [x] 本地已创建 `scripts/hermes_pre_fetch_klines.py`（Hermes 稳定入口 wrapper）
- [ ] **[云端]** 创建 `~/.hermes/scripts/qing_pre_fetch_klines.py` → 指向项目 wrapper
- [ ] **[云端]** 确认 `HERMES_REPO_ROOT` 环境变量指向正确路径
- [ ] **[云端]** 验证 pre_fetch 在云端网络环境下可正常访问东财 API（无防火墙拦截）
- [ ] **[云端]** 验证 SQLite WAL 文件在云端磁盘权限正常（可读写 `infra/data/`）
- [ ] **[云端]** pre_fetch 失败率 >20% 时，Hermes 发送告警通知
- [ ] **[云端]** 验收：盘中某标的价格进入介入区 → 自动收到买入信号/不买推送

---

## 当前推进任务

**当前状态**：Phase 0-4 核心代码全部实现完毕，本地测试通过（83/83）

**已完成**：
- ✅ Phase 0: K线缓存基础设施（SQLite + WAL + 06:30 pre-fetch）
- ✅ Phase 1: Agent prompt 买入确认模式（`stock_analyst.txt` 新增分支）
- ✅ Phase 2: Poll 候选筛选（`BuySignalCandidate` + 6 项条件判断）
- ✅ Phase 3: Agent 单票分析链路（`analysis_type="stock"` + 动态 payload）
- ✅ Phase 4: 全自动闭环（daily_state 同步 + 价格分桶去重 + 失效检测）

**待验证/待部署**：
1. **[本地]** ✅ 端到端测试：8/8 通过（候选检测 → alert → trigger → JSON payload）
2. **[本地]** ✅ 全量回归测试：91/91 通过
3. **[云端]** 部署 `hermes_pre_fetch_klines.py` wrapper 到 `~/.hermes/scripts/`
4. **[云端]** 验证 pre_fetch 在云端网络环境下可正常访问东财 API
5. **[云端]** 验收：盘中某标的价格进入介入区 → 自动收到买入信号/不买推送
