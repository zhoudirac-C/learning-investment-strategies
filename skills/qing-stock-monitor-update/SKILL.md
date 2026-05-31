---
name: qing-stock-monitor-update
description: |
  Update stock monitor configuration (watchlist, strategy_pack, positions) based on
  real-time market data and blogger (UP) latest views. Handles observation pool updates,
  position management, and technical inference when UP has not explicitly commented.
  Use when the user asks to update watchlist, observation pool, position strategy,
  or stock monitor configuration.
---

# qing-stock-monitor-update

## 目标

基于真实股价数据和博主最新观点，更新 `config/stock_monitor/` 下的三个配置文件：
- `watchlist.yaml` — 观察池 themes 和 stocks
- `strategy_pack.yaml` — 市场框架、指数规则、量化策略
- `positions.yaml` — 持仓管理、做T计划、风控

## 触发条件

- "更新观察池"
- "更新 stock monitor"
- "把新 theme 加到 watchlist"
- "看看持仓要不要调整"
- "今天收盘后更新策略"
- "生成明天的交易计划"

## 必读参考

1. `skills/qing-stock-monitor-update/references/qualitative-fields-spec.md` — 描述型字段规范
2. `skills/qing-stock-monitor-update/references/data-fetch-script.md` — 数据获取脚本规范
3. `skills/qing-stock-monitor-update/references/yaml-update-protocol.md` — YAML 更新协议
4. `skills/qing-stock-monitor-update/references/technical-inference.md` — 无 UP 观点时的技术推断规则
5. `skills/qing-stock-analysis/references/data-source-strategy.md` — 数据源策略与降级规则
6. `framework/technical-analysis-framework.md` — 技术工具层规则（轨道B）

## 工作流程

### Step 1: 获取真实数据

运行数据获取脚本：

```bash
cd ~/learning-investment-strategies
python3 skills/qing-stock-monitor-update/scripts/fetch_stock_data.py \
  --config-dir config/stock_monitor \
  --output /tmp/stock_data_$(date +%Y%m%d_%H%M).json
```

数据源优先级：
1. 运行环境原生金融数据能力
2. 东方财富实时行情（stock_monitor.py 已有）
3. glmv-stock-analyst/fetch_all.py（K线、基本面、主力资金、分时图）
4. 新浪财经/其他公开接口（降级）

降级规则：数据源不可用时标记 `degraded: true`，不阻断更新。

### Step 2: 检查 UP 最新观点

读取最近 3 天的内容：
- `knowledge/claims/claim-YYYYMMDD-*.yaml`
- `knowledge/wiki/每日复盘/YYYY-MM-DD.md`
- `sources/raw/财经/`（最近 3 天）

更新每个标的的 `up_mention_status`：
- `last_mentioned_date`
- `mention_context`
- `explicit_operation`（如有明确买/卖/持有/规避）
- `sentiment`（积极观察/中性提及/明确规避/未提及）

### Step 3: 更新 watchlist.yaml

**追加原则**：
- 新 theme → 追加到 `themes` 列表末尾
- 新 stock → 在对应 theme 的 `stocks` 列表内追加
- 旧 theme/stock 保留，除非用户明确要求删除

**每个 stock 的字段**：
```yaml
- code: "600246.SH"
  name: "万通发展"
  role: "pcie_switch_core"
  segment: "PCIe Switch"
  priority: "P1-核心"
  watch_reason: "..."
  sync_with_index: "..."
  confirm_with: ["ST得润", "寒武纪"]
  buy_setup:
    - "条件1"
    - "条件2"
  invalidation_setup:
    - "失效1"
    - "失效2"
  # 新增描述型字段
  up_mention_status:
    last_mentioned_date: "2026-05-28"
    mention_context: "博主在复盘视频中提到..."
    explicit_operation: null
    sentiment: "积极观察"
  technical_narrative:
    trend: "5日线上方运行"
    volume_character: "涨停放量"
    key_levels: ["支撑：15.0", "压力：17.5"]
    pattern: "突破平台后首板"
    note: "封单坚决"
  sector_narrative:
    relative_strength: "CPU链最强"
    money_flow: "主力连续2日净流入"
    leader_follower: "板块龙头"
    catalyst: "字节自研CPU"
    risk: "组内分化"
```

### Step 4: 更新 strategy_pack.yaml

**更新内容**：
- `today_snapshot`：市场环境、UP 基调、整体操作建议
- `market_framework.current_stage`：周期阶段（如情绪拐点/主升/调整）
- `market_framework.core_question`：当前核心问题
- `index_rules`：指数关键位（如 4055 支撑）
- `quant_entry_strategy`：基于收盘数据的量化介入点
- `sector_groups`：板块分组（如有新增板块）
- `agent_analysis_schedule`：大模型分析时间点（如需调整）

### Step 5: 更新 positions.yaml

**更新内容**：
- `latest_quote_snapshot`：最新行情快照
- `latest_up_bias`：UP 最新判断基调
- `today_key_signals`：今日关键信号
- 每个持仓的 `latest_monitor_reference`：最新价、涨跌幅
- 每个持仓的 `pnl`：浮动盈亏
- 每个持仓的 `today_plan`：明日操作计划（重置，不保留旧计划）

**today_plan 格式**：
```yaml
today_plan:
  - "【复盘定调】标的定性描述"
  - "【明日策略】持有/做T/减仓/清仓"
  - "【做T区间】低吸：X.XX-X.XX；高抛：X.XX-X.XX"
  - "【风控线】X.XX-X.XX，跌破且30分钟不能收回触发"
  - "【强度确认】板块同步条件"
  - "【禁忌】不追涨停/一致高开"
```

**无 UP 观点时的处理**：
- 基于 `technical_narrative` + `framework/technical-analysis-framework.md` 推断
- 必须写入 `inference_note`：
  ```yaml
  inference_note:
    basis: "UP未明确提及，基于技术框架推断"
    confidence: "中"
    key_assumption: "假设大盘不跌破4055"
    invalidation: "若放量跌破15.8，推断失效"
    suggested_action: "等回踩15.8-16.0区间企稳后轻仓试探"
  ```

### Step 6: 验证

```bash
cd ~/learning-investment-strategies
python3 -m qing_investment.stock_monitor --status
python3 -m qing_investment.stock_monitor --analysis-context
```

确认：
- YAML 解析无错误
- 输出包含新增的描述型字段
- 大模型分析上下文格式正确

### Step 7: Git 提交

```bash
cd ~/learning-investment-strategies
git add config/stock_monitor/watchlist.yaml config/stock_monitor/strategy_pack.yaml
git commit -m "monitor: update watchlist/strategy for $(date +%Y-%m-%d)"
# positions.yaml 已 gitignored，不提交
```

## 关键纪律

1. **观察池追加，不替换**：新 theme/stock 追加到末尾，旧的不删。
2. **推断必须标注**：无 UP 观点时的技术推断必须写 `inference_note`。
3. **数据源降级**：不可用时不编造数据，标记 degraded。
4. **验证后提交**：每次更新后运行 `--status` 和 `--analysis-context` 确认。
5. **区分轨道**：技术推断只引用 `framework/technical-analysis-framework.md`（轨道B），不混淆市场认知 claims（轨道A）。

## 禁止事项

- 不编造价格、财务、新闻或博主观点。
- 不把推断伪装成 UP 原话。
- 不删除旧 theme，除非用户明确说移除。
- 不跳过验证直接提交。
- 不将单日语境直接提升为长期 framework。
