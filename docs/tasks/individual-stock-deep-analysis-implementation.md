# 个股深度分析（竞价+分时）— 实施任务清单

> 依据：`docs/design/individual-stock-deep-analysis-design.md` v1.0 + 评审补充（第6-10章）
> 原则：完成一个打钩一个，再推进下一个。P0 优先，P1 次之，P2/P3 待 P0+P1 跑通后迭代。
> 标记：`[x]` = 已完成，`[ ]` = 待完成，`[-]` = 跳过/不实施

---

## Phase 0: 现有能力盘点

### 0.1 盘点 stock_monitor.py 现状
- [ ] 确认 `DEFAULT_AGENT_ANALYSIS_SCHEDULE` 9个时间节点中，哪些需要改造为"个股深度分析模式"
- [ ] 确认 `format_agent_analysis_context()` 当前注入的上下文字段清单
- [ ] 确认 `format_agent_json_context()` 当前注入的 JSON 字段清单
- [ ] 确认 `_agent_context_data()` 中 positions / watchlist 的数据结构
- [ ] **验证方式**：打印一次 `format_agent_json_context()` 输出，确认现有字段

### 0.2 确认成本数据可用性
- [ ] 检查 `positions.yaml` 中是否已有 `cost`、`shares` 字段，格式是否统一
- [ ] 检查 `positions.yaml` 中 `pnl.unrealized_profit_pct` 是否已计算，若未计算需在 `_agent_context_data()` 中实时计算
- [ ] **验证方式**：`python -c "import yaml; print(yaml.safe_load(open('config/stock_monitor/positions.yaml'))['accounts'][0]['positions'][0].keys())"`

### 0.3 确认竞价数据源
- [ ] 验证腾讯财经 API 是否能获取竞价数据（09:25 撮合价、竞价量）
- [ ] 验证东财 API 是否能获取竞价阶段 9:20-9:25 的价格轨迹
- [ ] 若两者都不支持竞价轨迹，确认降级方案（仅用 9:25 快照 + 近5日竞价均值）
- [ ] **验证方式**：写个临时脚本 09:25 跑一次，打印原始返回 JSON

---

## Phase 1: 数据层 — 昨日特征摘要

### 1.1 实现 `_build_yesterday_summary()`
- [ ] 从 `state.json` 的 `last_quote_snapshot` 提取基础行情（close/open/high/low/change_pct/volume/amount）
- [ ] 从 `daily_state.json` 提取市场阶段、方向判断
- [ ] 从 `strategy_pack.yaml` / `watchlist.yaml` 提取 `entry_zone` 状态和 `is_limit_up` / `consecutive_limit_ups` / `weak_board` / `board_open_count` / `first_board_time` / `board_seal_ratio`
- [ ] 从 `state.json` 提取 `intraday_pattern`（若已有）
- [ ] 计算 `turnover_rate` / `amplitude` / `volume_ratio` / `vs_ma5` / `vs_ma10` / `near5d_return`
- [ ] **产出物**：`config/stock_monitor/daily_review_summary.json` 文件（含设计文档1.1全部18个字段）
- [ ] **验证方式**：单元测试 — mock state.json + strategy_pack → 验证输出 JSON 字段完整性和数值正确性

### 1.2 实现 `_load_yesterday_summary()` 带 fallback
- [ ] 优先读取 `daily_review_summary.json`
- [ ] 若文件不存在 → fallback 到 `state.json` 的 `last_quote_snapshot`（仅7个基础字段）
- [ ] 若 `last_quote_snapshot` 也不完整 → fallback 到 K线缓存 SQLite + 腾讯财经 API（仅 OHLC）
- [ ] 每次读取记录日志（来源 + 字段完整度）
- [ ] **验证方式**：单元测试 — 三种 fallback 路径分别验证

### 1.3 实现 `_save_yesterday_summary()`
- [ ] 接收 `_build_yesterday_summary()` 的输出 dict
- [ ] 写入 `config/stock_monitor/daily_review_summary.json`（带日期键，如 `"2026-06-11": {...}`）
- [ ] 异常处理：写入失败时记录 error log，不抛异常阻断主流程
- [ ] **验证方式**：单元测试 — 写入后读取 → 对比原 dict 和读取 dict 一致性

### 1.4 收盘复盘自动提取 summary
- [ ] 修改 15:20 cron 的 prompt，要求 LLM 在输出末尾附带结构化复盘数据（`daily_review_summary` 格式）
- [ ] 修改 `stock_monitor.py`，在收盘复盘执行后解析 LLM 输出中的结构化数据，调用 `_save_yesterday_summary()`
- [ ] 若 LLM 未返回结构化数据 → 从 `quote_snapshot` + 规则自动计算补充（不依赖 LLM）
- [ ] **验证方式**：手动跑一次收盘复盘 → 检查 `daily_review_summary.json` 是否正确写入

---

## Phase 2: 数据层 — 竞价快照（P0）

### 2.1 实现基础 `_auction_snapshot()`
- [ ] 调用腾讯财经 API 或东财 API，获取 09:25 撮合结果
- [ ] 提取字段：`auction_price`、`auction_change_pct`、`auction_volume`
- [ ] 计算字段：`auction_volume_ratio` = 竞价量 / 近5日竞价量均值（需提前缓存近5日竞价量）
- [ ] **产出物**：基础6字段的 dict
- [ ] **验证方式**：09:25 手动跑一次，对比同花顺/通达信显示的竞价数据

### 2.2 补充评审建议字段（9:20-9:25 轨迹）
- [ ] 确认数据源是否支持 9:20-9:25 每分钟的价格数据
- [ ] 若支持：计算 `auction_amplitude`、`last5min_high_pct`、`last5min_low_pct`、`auction_trend_920_925`
- [ ] 若不支持：降级为 `"auction_trend_920_925": "unknown"`，记录 warning log
- [ ] 新增 `auction_vs_yesterday_volume` = 竞价量 / 昨日全天成交量
- [ ] 新增 `unmatched_buy_ratio`（需 Level-2 数据，若不支持标记为 `null`）
- [ ] **验证方式**：09:25 手动跑一次，打印全部字段，确认无异常

### 2.3 09:26 cron 集成竞价快照
- [ ] 在 `stock_monitor.py` 的 09:26 触发逻辑中，调用 `_auction_snapshot()` 并将结果注入 `quote_snapshot` 或独立字段
- [ ] 确保 `_load_yesterday_summary()` 在 09:26 触发前执行，竞价数据 + 昨日 summary 同时就绪
- [ ] **验证方式**：`python -m qing_investment.stock_monitor --agent-json-context --agent-any-time`（mock 09:26 时间）→ 检查 JSON 输出是否含 `auction_snapshot`

---

## Phase 3: 数据层 — 持仓成本注入（P0）

### 3.1 实时计算持仓浮盈
- [ ] 在 `_agent_context_data()` 中，遍历 `enriched_positions` 时，读取 `cost` 和 `shares`
- [ ] 计算 `unrealized_pct` = (latest - cost) / cost * 100
- [ ] 计算 `cost_protection_line`（如浮盈>10%则保护线为成本+5%，浮盈<5%则保护线为成本）
- [ ] 将 `avg_cost`、`unrealized_pct`、`cost_protection_line` 注入每个 position dict
- [ ] **验证方式**：单元测试 — mock positions（cost=100, latest=110）→ 验证 unrealized_pct=10

### 3.2 JSON context 验证
- [ ] 运行 `python -m qing_investment.stock_monitor --agent-json-context --agent-any-time`
- [ ] 检查输出 JSON 中 `positions[0]` 是否包含 `avg_cost`、`unrealized_pct`、`cost_protection_line`
- [ ] **验证方式**：jq 或 python 脚本断言字段存在

---

## Phase 4: 数据层 — 昨日特征扩展（P1）

### 4.1 龙虎榜字段扩展（个股级）
- [x] 调研：akshare `stock_lhb_stock_detail_em()` 可用，已集成到 `_build_yesterday_summary()`
- [x] 在 `_build_yesterday_summary()` 中增加 `dt_seat_type`、`dt_top_buy_behavior`、`dt_is_pure_hot_money`、`board_quality`、`dragon_tiger_net`
- [x] **验证方式**：已实测 002409 2026-06-11 龙虎榜数据完整

### 4.1b 龙虎榜全市场总榜交叉校验（新增）
- [ ] 实现 `_fetch_daily_dragon_tiger_board()` — 调用 `ak.stock_lhb_detail_em(start_date, end_date)` 获取当日全市场龙虎榜总榜
- [ ] 实现交叉过滤逻辑：持仓池∪观察池→`watch_dt_items`；全市场净买入TOP5→`dt_nettop5`；按theme汇总→`dt_sector_summary`
- [ ] 集成到 `_agent_context_data()` — 将产出注入 `market_snapshot` 下的新增字段
- [ ] **集成到 text context** — 在 format_agent_analysis_context() 中添加龙虎榜总榜摘要段
- [ ] **时效性控制**：仅 15:20 收盘复盘后执行（龙虎榜数据通常 16:00-17:00 发布）
- [ ] **验证方式**：mock 收盘复盘时间 → 检查 JSON context 中含 `dragon_tiger_board` 字段
- [ ] **设计文档**：已更新 §7.4
- [ ] **参考**：akshare `stock_lhb_detail_em(start_date='20260610', end_date='20260610')` 返回列含 `['代码','名称','收盘价','涨跌幅','龙虎榜净买额','龙虎榜买入额','龙虎榜卖出额','换手率','上榜原因']`

### 4.2 板块梯队对比
- [ ] 在 `_agent_context_data()` 中，对每个持仓股的 `theme`，查找同 theme 的其他股票
- [ ] 按 `pct_change` 排序，标记 tier1/tier2/tier3（或按 watchlist 中的 `role` 标记）
- [ ] 将 `sector_tier` 注入上下文
- [ ] **验证方式**：检查 JSON context 中某持仓股是否含 `sector_tier` 字段

### 4.3 收盘复盘输出 tomorrow_scenarios
- [ ] 修改 `cron_closing.txt`，明确要求 LLM 输出 `"tomorrow_scenarios"` JSON 块
- [ ] 修改 `_save_yesterday_summary()`，解析并保存 `tomorrow_scenarios`
- [ ] **验证方式**：手动跑一次收盘复盘 → 检查 summary JSON 中 `tomorrow_scenarios` 含 strong/weak/divergence 三个分支

---

## Phase 5: Prompt 层 — 核心节点重写（P1）

### 5.1 重写 `cron_opening.txt`（09:26 竞价后）✅
- [x] 保留现有角色设定和 daily_state 输出要求
- [x] **新增**：要求 LLM 结合昨日复盘的 `tomorrow_scenarios` 做"剧本验证"
- [x] **新增**：输出格式增加 — "昨日预判 vs 今日竞价对比"（scenario_validation JSON 块）
- [x] **新增**：若竞价数据与预判情景不符，说明哪里超预期/低于预期
- [x] 字数限制：200字 → 250字
- [x] **验证方式**：prompt 文件加载检查通过

### 5.2 重写 `cron_open_confirm.txt`（09:45 开盘15分钟）✅
- [x] 保留现有角色设定和 daily_state 输出要求
- [x] **新增**：注入"持仓类型分支指令" — 根据 `position_type`（limit_up/weak_board/floating_loss/trend）选择对应框架
- [x] **新增**：明确要求结合 `avg_cost` 和 `unrealized_pct` 分析
- [x] **新增**：要求判断前15分钟是"阶梯式堆量"还是"脉冲式放量"
- [x] **新增**：要求对比 `sector_tier`（同板块龙一/龙二表现）
- [x] 字数限制：150字 → 200字
- [x] 同时实现了 Phase 6.2（position_type 计算 + 注入 text context）

### 5.3 重写 `cron_tail_condition.txt`（14:52 尾盘）✅
- [x] 保留现有角色设定
- [x] **新增**：要求每只持仓输出"明日剧本预判"（强修复/弱震荡/强分歧的概率和条件）
- [x] **新增**：要求烂板票输出"明日竞价关注要点"（龙虎榜席位回顾）
- [x] **新增**：要求输出 `tomorrow_scenarios` JSON 块（含 three-scenario 结构，供次日09:26使用）
- [x] **验证方式**：prompt 文件加载检查通过

### 5.4 微调其他节点 ✅
- [x] `cron_morning_confirm.txt`（10:00）：增加"09:45假设是否被验证"回顾（audit_0945 字段）
- [x] `cron_opportunity_scan.txt`（10:30）：保持现状，不修改
- [x] `cron_noon_review.txt`（11:20）：增加"午后预案"前瞻（scenario_foresight 字段）
- [x] `cron_afternoon_risk.txt`（13:10）：增加"持仓成本保护线是否触发"检查（protection_line_check 字段）
- [x] `cron_midday.txt`（14:00）：仅加一行"尾盘前瞻"，保持精简
- [x] **验证方式**：所有 9 个 prompt 文件均含 daily_state 输出块，格式一致

---

## Phase 6: Prompt 层 — Context Builder 改造

### 6.1 注入 yesterday_summary + auction_snapshot ✅（Phases 1-2 已提前完成）
- [x] `format_agent_analysis_context()` 已有"=== 昨日特征摘要 ==="段落（第2824行）
- [x] `format_agent_analysis_context()` 已有"=== 竞价快照 ==="段落（第2840行）
- [x] `format_agent_json_context()` 通过 `_agent_context_data()` 返回 `yesterday_summary` 和 `auction_snapshot`

### 6.2 注入持仓类型标记 ✅（Phase 5 已合并实施）
- [x] `_agent_context_data()` 中计算 `position_type`（第2626-2646行）
- [x] 规则：limit_up / weak_board / floating_loss / trend
- [x] `format_agent_analysis_context()` 输出到 text context（第2868-2872行）

### 6.3 重组输出格式 ✅
- [x] 合并【盘面】+【全A锚】→ 单一【盘面】段（全A锚合并）
- [x] 拆分【持仓池】→ 【重点分析】(1-2只, 80-100字, 含持仓类型分支) + 【其他持仓】(每只15字)
- [x] 简化【观察池】→ 最多3只，每只15字
- [x] 同步更新 daily_review_context 模板（两处保持一致）
- [x] 更新测试断言（assert 新旧模板差异）
- [x] 验证：49/49 pytest 通过

---

## Phase 7: 测试与验收

### 7.1 模拟盘后测试 — 09:26 竞价分析
- [ ] 准备 mock 数据：某持仓股昨日烂板 + 今日竞价低开-3% + 无承接
- [ ] 运行 `python -m qing_investment.stock_monitor --agent-json-context --agent-any-time --mock-time 09:26`
- [ ] 检查 LLM 输出是否激活"烂板次日处理框架"，是否建议"开盘即减仓"
- [ ] **通过标准**：分析结论与预期一致，且附带条件（"若X则Y"）

### 7.2 模拟测试 — 09:45 持仓类型分支
- [ ] 准备4组 mock 数据（连板/烂板/趋势/浮亏各一组）
- [ ] 分别触发分析，检查 LLM 输出是否正确引用对应分支框架
- [ ] **通过标准**：4组全部正确激活对应分支，无混淆

### 7.3 模拟测试 — 收盘复盘 tomorrow_scenarios
- [ ] mock 一个复杂的交易日（多持仓、有烂板、有趋势股）
- [ ] 运行收盘复盘分析，检查输出是否含 `tomorrow_scenarios` JSON 块
- [ ] 检查 JSON 块是否含 strong/weak/divergence 三个分支及概率
- [ ] **通过标准**：JSON 可解析，三个分支概率之和≈100%

### 7.4 次日实盘观察（至少3个交易日）
- [ ] Day 1：观察 09:26 输出质量，对比实际开盘走势
- [ ] Day 2：观察 09:45 输出质量，对比实际15分钟后走势
- [ ] Day 3：观察收盘复盘质量，检查次日09:26的"剧本验证"是否有对比基准
- [ ] 记录每日：分析准确率、token 用量、输出字数
- [ ] **通过标准**：3天中至少2天的"重点分析"方向判断正确

### 7.5 Token 成本监控
- [ ] 统计3天平均每次分析的 token 数（输入+输出）
- [ ] 若单次 >4000 tokens → 考虑压缩"其他持仓"到每只10字，或减少观察池数量
- [ ] **通过标准**：单次分析平均 token 数 ≤4000（输入≈3000 + 输出≈600）

---

## Phase 8: 迭代优化（P2/P3）

### 8.1 龙虎榜席位性质数据源（P2）
- [ ] 调研 akshare / 东财 API 龙虎榜数据接口
- [ ] 实现 `fetch_dragon_tiger_detail(code, date)` → 返回席位类型、买一行为
- [ ] 集成到 `_build_yesterday_summary()`
- [ ] **前置条件**：Phase 1-7 全部跑通且稳定

### 8.2 分钟级量能数据（P3）
- [ ] 调研数据源是否支持 1分钟/5分钟 K线
- [ ] 若支持：实现 `first_15min_volume_by_5min()` → 返回 `[v1, v2, v3]`
- [ ] 若支持：实现 `price_vs_vwap_at_0945()`
- [ ] 集成到 `_auction_snapshot()` 或独立函数
- [ ] **前置条件**：Phase 1-7 跑通，且 09:45 分析经常不准

### 8.3 Prompt 持续调优
- [ ] 根据7.4的实盘观察记录，识别 LLM 经常误判的场景
- [ ] 针对性补充 few-shot 示例或修正分支框架条件
- [ ] 每月回顾一次，更新 `docs/design/individual-stock-deep-analysis-design.md`

---

## 当前推进任务

**当前状态**：Phase 5 已完成 ✅ | Phase 6 待启动

**已完成**：
- Phase 0-3: 数据盘点 + 昨日摘要 + 竞价快照 + 持仓成本注入 ✅
- Phase 4: 板块梯队 + 龙虎榜个股 + 全市场总榜交叉校验 ✅
- Phase 5: 全部 9 个 prompt 文件重写（含 Phase 6.2 position_type 计算）✅
  - cron_opening.txt: 剧本验证 + 竞价对比
  - cron_open_confirm.txt: 持仓类型分支 + 堆量判断 + sector_tier 对比
  - cron_tail_condition.txt: 明日预判 + 烂板要点 + tomorrow_scenarios 输出
  - 其他 6 个节点微调保护线检查/午后预案/09:45假设回顾

**下一步行动**：
- Phase 6: Context Builder 改造（已完成 6.1/6.2/6.3 全部子任务）✅
2. Phase 7: 测试与验收
3. Phase 8: 迭代优化
