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

2. `skills/qing-stock-monitor-update/references/qualitative-fields-spec.md` — 描述型字段规范
3. `skills/qing-stock-monitor-update/references/data-fetch-script.md` — 数据获取脚本规范（含输出数据读取方法）
4. `skills/qing-stock-monitor-update/references/yaml-update-protocol.md` — YAML 更新协议
5. `skills/qing-stock-monitor-update/references/technical-inference.md` — 无 UP 观点时的技术推断规则
6. `skills/qing-stock-monitor-update/references/patch-disambiguation-pitfall.md` — Patch 工具歧义匹配陷阱与解决
7. `skills/qing-stock-monitor-update/references/narrative-bulk-update-from-review.md` — 从复盘文档批量更新 narrative 的规范流程与常见陷阱
8. `skills/qing-stock-monitor-update/references/data-source-fallback-chain.md` — 数据源降级时的备用获取方案（腾讯 API、venv pip 修复、glmv 脚本）
9. `skills/qing-stock-monitor-update/references/claims-consistency-check.md` — **Claims 一致性校验**：更新 strategy_pack 前必须与 claims 交叉验证，防止策略与博主纪律矛盾
10. `skills/qing-stock-monitor-update/references/sector-rotation-rules-format.md` — **sector_rotation_rules 格式规范**：list of dicts 格式，引用 sector_groups 的 id
11. `framework/technical-analysis-framework.md` — 技术工具层规则（轨道B）
12. `skills/qing-stock-monitor-update/references/llm-hallucination-prevention.md` — **LLM 幻觉防范**：cron 任务生成股价数据时的验证与约束（含批量更新 cron prompt 模板）

## 工作流程

### Step 0: 前置检查

1. **`git pull`**：确保本地文件是最新版本，避免基于旧版本修改后产生冲突。
2. **检查数据是否已同步**：若 watchlist 的 `today_snapshot`、`technical_narrative`、`sector_narrative` 已包含复盘文档中的数据，不要重复写入。向用户报告当前同步状态，询问是否需要基于**今早动态**追加更新。
3. **区分两种更新模式**：
   - **模式 A（基础）**：更新已有票的 narrative + today_snapshot
   - **模式 B（极易遗漏）**：扫描复盘文档中的"关注地位方向""核心思路""方向提示"段落，提取 UP 新提到的标的，新增到 watchlist 并在 strategy_pack 中补充 entry_points
   - **必须先执行模式 A，再执行模式 B，两步都完成才算完整**

### Step 1: 获取真实数据

运行数据获取脚本：

```bash
cd ~/learning-investment-strategies
python3 skills/qing-stock-monitor-update/scripts/fetch_stock_data.py \
  --config-dir config/stock_monitor \
  --output /tmp/stock_data_$(date +%Y%m%d_%H%M).json
```

**读取输出数据**：`stocks` 字段是列表（list），不是字典。必须先转换为 `code -> info` 映射：

```python
import json
with open('/tmp/stock_data_YYYYMMDD_HHMM.json') as f:
    data = json.load(f)
stocks_list = data.get('stocks', [])
stock_dict = {s['code']: s for s in stocks_list if 'code' in s}
# 市场指数：data['market']['indexes']
```

数据源优先级：
1. 运行环境原生金融数据能力
2. 东方财富实时行情（stock_monitor.py 已有）
3. glmv-stock-analyst/fetch_all.py（K线、基本面、主力资金、分时图）
4. **腾讯财经 API（curl，无需 Python 包，备用首选）**
5. 新浪财经/其他公开接口（降级）

降级规则：数据源不可用时标记 `degraded: true`，不阻断更新。详见 `references/data-source-fallback-chain.md`。

### Step 2: 检查 UP 最新观点（模式 A + 模式 B）

读取最近 3 天的内容：
- `knowledge/claims/claim-YYYYMMDD-*.yaml`
- `knowledge/wiki/每日复盘/YYYY-MM-DD.md`
- `sources/raw/财经/`（最近 3 天）

**模式 A：更新已有标的 up_mention_status**
- `last_mentioned_date`
- `mention_context`
- `explicit_operation`（如有明确买/卖/持有/规避）
- `sentiment`（积极观察/中性提及/明确规避/未提及）

**模式 B：提取 UP "关注方向"（极易遗漏，必须执行）**
- 扫描复盘文档中的"关注地位方向""核心思路""方向提示""强势股"等段落
- 提取 UP 明确提示要关注的标的（即使当前不在 watchlist 中）
- 检查这些标的是否已在 watchlist 中：
  - **若不存在**：新增 theme 或追加到对应 theme，写入完整字段（含 narrative）
  - **若已存在**：更新 narrative，并在 `watch_reason` 中追加 UP 最新提示
- 无论是否新增，都必须在 strategy_pack.yaml 的 `entry_points` 中补充操作策略
- **示例命令**：`grep -n "关注地位方向\|核心思路\|鼎龙股份\|裕太微" sources/raw/财经/复盘*.md`

### Step 2.5: 同步更新 strategy_pack.yaml（必须与 watchlist 同步，不可遗漏）

**不可遗漏**：只更新 watchlist 而不更新 strategy_pack 会导致观察池无法指导实际交易。用户明确反馈："不只是更新watchlist 你每次更新的时候都要把操作策略，介入股价都加上，不然什么时候能买入呢？观察有啥有用呢"

**更新前必须执行 claims 一致性校验**（详见 `references/claims-consistency-check.md`）：
1. 扫描最近 3 天的 claims，查找与目标标的相关的博主观点
2. 若 claim 中博主明确说"不追高""韭菜行为""只观察"，对应标的必须配置为 `entry_zone: 只观察不介入`，`position_ratio: 0`
3. 在 `note` 中标注 claim 来源（如"来源：claim-20260602-002.yaml"）
4. 常见矛盾：给"已提前提示，现在追是韭菜"的方向配介入区间 → 必须修正为只观察

**更新内容**：
- `quant_entry_strategy.entry_points`：为每个重点标的补充**具体介入区间、仓位、触发条件、失效条件**
- `quant_entry_strategy.position_advice`：更新空仓/满仓的操作建议
- `market_framework`：更新周期阶段、核心问题
- `index_rules`：更新指数关键位

- `entry_zone` 填写规范：
  - **必须提供具体价格数字**，不能写"近期平台附近""等分歧后缩量回踩"等模糊描述
  - 若数据源可用：基于当日收盘价，回踩 5-7% 计算（如收盘 28.5 → 介入区间 26.5-27.5）
  - **若数据源降级无法获取实时价格**：
    - **诚实说明**："数据源降级，无法获取实时价格。需手动填写"
    - **提供计算规则**："基于当日收盘价，回踩 5-7% 介入"
    - **绝不编造虚假价格**（用户会验证，编造价格会导致信任崩塌）
    - **备用方案**：使用腾讯财经 API（curl）获取价格，详见 `references/data-source-fallback-chain.md`
  - 对于已大涨的票（如单日 +18%）：介入区间需等更充分调整（10-15%）

**position_ratio 填写规范**：
- 必须提供具体仓位（如"1成""0.5成"）
- 高弹性/高风险票降低仓位（如裕太微 0.5 成）
- 空仓总仓位控制在 6 成以内（因新增多个方向）

**无持仓票不配置 stop_loss**：
- 用户明确："没有持仓的不用止损，主要是介入区间和操作策略"
- `stop_loss` 字段只用于已有持仓的票
- 观察池新票只配置 `entry_zone` + `invalidation`（失效条件）

### Step 3: 更新 watchlist.yaml

**追加原则**：
- 新 theme → 追加到 `themes` 列表末尾
- 新 stock → 在对应 theme 的 `stocks` 列表内追加
- 旧 theme/stock 保留，除非用户明确要求删除
- **必须扫描复盘文档中的"关注地位方向""核心思路"段落，提取 UP 新提到的标的**
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

**`index_rules` 格式兼容性（必读）**：
- 代码对通用格式（`trigger_condition: close_below`）支持不完整，存在漏报风险。
- **必须同时写 legacy 格式兜底**：`- trend_defense: 4070` 作为 `trigger_condition: close_below` 的兼容备选。
- 实际验证方法：更新后运行 `python -m qing_investment.stock_monitor --ignore-trading-time`，检查 `alert_decision_log` 是否生成对应记录；若未生成，说明通用格式未被支持，需补 legacy 格式。

**`sector_rotation_rules` 关键字段**：
- 格式：**list of dicts**，每个 rule 有独立 `id`
- `offensive_group_ids` / `defensive_group_ids` / `avoid_group_ids`：引用 `sector_groups` 中定义的 `id`，不是字符串列表
- `min_spread_pct`：进攻/防御组均涨幅差阈值（默认 1.0，复盘后可视情况上调）
- `min_red_ratio_spread`：红盘率差阈值
- `require_offensive_positive: true`（可选）：防止"跌得少"被误判为"进攻回流"
- 详见 `references/sector-rotation-rules-format.md`

**`sector_groups` 同步纪律**：
- 新增持仓标的必须加入对应 sector_group，否则不会被纳入板块轮动计算。
- 已清仓标的必须从 sector_group 中移除，否则会拖累组平均涨幅，产生错误的板块轮动信号。

### Step 5: 更新 positions.yaml

**更新内容**：
- `latest_quote_snapshot`：最新行情快照
- `latest_up_bias`：UP 最新判断基调
- `today_key_signals`：今日关键信号
- 每个持仓的 `latest_monitor_reference`：最新价、涨跌幅
- 每个持仓的 `pnl`：浮动盈亏
- 每个持仓的 `today_plan`：明日操作计划（重置，不保留旧计划）

**持仓变动处理**：
- **新建持仓**：添加完整字段（code, name, shares, cost, reduce_zone, risk_zone, account, open_date, note, today_plan）
- **减仓**：更新 shares 和 cost（用户会提供新的 cost），在 note 中标注"减仓后X股（原Y股）"
- **清仓**：从 `positions` 列表移除，添加到 `closed_positions`，记录卖出价和盈亏
- **账户重命名**：若用户要求更改账户名称，同步更新所有 `account` 字段和 `strategy_summary` 中的描述

**价格区间字段规范（必读）**：
- `risk_zone`：风控区间，格式 `"44.5-45.5"`。代码优先读取此字段，触发条件为 `latest <= risk_zone[1]`（即区间上限）。
- `risk_line`：单点风控线（如 `44.5`）。代码兼容作为 `risk_zone` 的 fallback，解析为 `(44.5, 44.5)`，触发条件为 `latest <= 44.5`。
- `reduce_zone`：减仓观察区间，格式 `"41.15-42.5"`。当 `latest` 落入此区间时触发减仓观察提醒。
- **关键陷阱**：若只配 `risk_line: 44.5` 而期望区间触发（如 44.5-45.5），必须用 `risk_zone: "44.5-45.5"`。
- **`positions.example.yaml` 必须使用 `risk_zone` 而非 `risk_line`**：示例文件作为模板应使用推荐字段名，避免复制后形成旧习惯。
- **高危漏报**：若持仓未配置 `reduce_zone` 或 `risk_zone`/`risk_line`，`evaluate_position_alerts()` 将完全跳过该持仓，导致跌停/大跌无任何提醒。更新时必须逐条确认每个持仓都配置了价格区间字段。

**已清仓标的处理**：
- 已清仓标的必须移入 `closed_positions`，同时从 `positions` 列表中删除。
- 若已清仓标的仍留在 `positions` 中，会继续触发减仓/风控提醒，产生配置滞后误报。

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
6. **区分轨道**：技术推断只引用 `framework/technical-analysis-framework.md`（轨道B），不混淆市场认知 claims（轨道A）。
7. **持仓更新必须完整**：不能只改股数而忽略 `today_snapshot`、`strategy_summary` 和 `today_plan` 的同步更新。
8. **必须同步更新 strategy_pack**：只更新 watchlist 不更新 strategy_pack 是严重遗漏。entry_points 必须包含具体介入区间、仓位、触发条件。
9. **绝不编造价格**：数据源降级时诚实说明，提供计算规则，不编造虚假价格。
10. **区分两种更新模式**：模式 A（已有票更新）+ 模式 B（UP 新方向提取），两步都完成才算完整。
11. **claims 一致性校验**：更新 strategy_pack 前必须扫描 claims，确认策略不与博主最新纪律矛盾。若 claim 中博主明确说"不追高"/"韭菜行为"，对应标的必须配置为"只观察不介入"。
12. **sector_rotation_rules 格式**：必须使用 list of dicts，引用 sector_groups 的 id。详见 `references/sector-rotation-rules-format.md`。

## 从复盘文档批量更新 narrative 的规范流程

当用户要求"把复盘文档的市场数据、板块涨跌、个股表现提取到 watchlist 对应票的 technical_narrative 和 sector_narrative 中"时，按以下流程执行：

### 前置检查
1. **先 `git pull`**：确保本地 watchlist.yaml 是最新版本，避免基于旧版本修改后产生冲突。
2. **定位复盘文档**：在 `docs/` 或 `sources/raw/财经/` 中找最新复盘文件（命名格式：`收盘监控复盘_YYYY-MM-DD.md` 或 `复盘：YY-MM-DD：...`）。
3. **提取关键数据**：
   - 指数收盘：上证、深证、创业板、科创50的收盘价和涨跌幅
   - 板块表现：各主题（CPU自研链、MLCC、半导体、防御等）的涨跌 summary
   - 个股数据：复盘文档"附：今日关键数据速查"表中的收盘价、涨跌幅、持仓盈亏

### 更新流程
1. **读取 watchlist.yaml 完整内容**（不带 offset/limit），确认目标票在哪些 theme 中出现。
2. **提取 UP "关注方向"（模式 B，极易遗漏）**：
   - 扫描复盘文档中的"关注地位方向""核心思路""方向提示""强势股"等段落
   - 提取 UP 明确提示要关注的标的（即使当前不在 watchlist 中）
   - 用 `grep` 或 Python 检查这些标的是否已在 watchlist 中
   - **若不存在**：新增 theme 或追加到对应 theme，写入完整字段（含 narrative）
   - **若已存在**：更新 narrative，并在 `watch_reason` 中追加 UP 最新提示
   - **示例命令**：`grep -n "关注地位方向\|核心思路\|鼎龙股份\|裕太微" sources/raw/财经/复盘*.md`
3. **更新已有票的 narrative（模式 A）**：
   - 同一票多 theme 处理：若某票出现在多个 theme 中，**每个出现位置都要更新**
   - 无 narrative 的票插入：在 `invalidation_setup` 之后插入新块，注意保留换行
4. **字段内容规范**：
   - `technical_narrative.trend`：必须包含日期和涨跌幅（如"6月1日-2.10%跌破成本"）
   - `technical_narrative.note`：必须包含收盘价、成本线（持仓票）、板块 context
   - `sector_narrative.relative_strength`：必须包含该票在板块内的相对位置（如"CPU链内偏弱""MLCC组最强"）
   - `sector_narrative.risk`：必须包含当日观察到的具体风险（如"组内分化严重，ST得润+5%但万通-2.1%"）
5. **today_snapshot 同步更新**：
   - `fetch_time`：更新为当前时间
   - `market_summary`：用复盘文档中的精确指数数据重写
   - `stocks_with_data`：更新为复盘文档中的收盘价和涨跌幅
   - `overall_action`：基于复盘结论重写

### 常见格式陷阱
- **换行缺失**：正则替换或字符串拼接时，`invalidation_setup` 最后一行与 `technical_narrative:` 之间缺少 `\n`，导致 YAML 解析为 `None`。修复：插入前检查 `invalidation_setup` 块末尾是否有换行，没有则补一个。批量插入时尤其注意：Python 正则替换的替换字符串必须以 `\n    technical_narrative:` 开头，而非直接拼接在前一行末尾。
- **多位置重复票**：如 `000636.SZ` 既是万通发展又是风华高科（不同 theme），更新时必须通过 `role` 字段区分（`pcie_switch_core` vs `mlcc_mainboard_core`），不能仅按 code 匹配。
- **同一 code 不同 name 的票被误匹配**：仅按 `code` 批量替换时，可能将万通发展的 narrative 错误写到风华高科上。修复：匹配时必须同时检查 `code` + `name` + `role`，用三者组合精确定位。
- **YAML 验证**：每次更新后用 `yaml.safe_load()` 验证文件可解析，确认所有目标票的 narrative 字段不为 `None`。

### 推荐方式：Python 批量更新（优于 Patch）

对于批量更新 narrative（涉及多票、多 theme、同一票多位置），**强烈推荐使用 Python `yaml.safe_load` + `yaml.dump` 而非 patch 工具**。

**原因**：
- Patch 工具对 YAML 缩进敏感，歧义匹配风险高
- 同一票出现在多个 theme 中时，patch 只能替换第一处匹配
- 插入新 narrative 块时，换行缺失会导致 YAML 解析失败

**Python 批量更新模板**：

```python
import yaml
import json

# 1. 加载数据
with open('/tmp/stock_data_YYYYMMDD_HHMM.json') as f:
    stock_data = json.load(f)
stock_dict = {s['code']: s for s in stock_data['stocks']}

# 2. 加载 watchlist
with open('config/stock_monitor/watchlist.yaml') as f:
    watchlist = yaml.safe_load(f)

# 3. 准备复盘数据映射（从复盘文档提取）
review_data = {
    '000636.SZ': {
        'name': '风华高科',  # 用于校验，防止 code-name 错位
        'pct': 8.83,
        'note': '6月2日+8.83%...',
        'sector': 'MLCC组最强...',
        'risk': '普涨共振...',
    },
    # ... 其他票
}

# 4. 遍历更新（自动处理同一票多 theme）
for theme in watchlist.get('themes', []):
    for stock in theme.get('stocks', []):
        code = stock.get('code')
        if code in review_data:
            d = review_data[code]
            # 必须校验 name 匹配，防止错位
            if stock.get('name') == d['name']:
                stock['technical_narrative'] = {
                    'trend': f"6月2日{d['pct']:+.2f}%...",
                    'volume_character': '...',
                    'key_levels': ['支撑：...', '压力：...'],
                    'pattern': '...',
                    'note': d['note']
                }
                stock['sector_narrative'] = {
                    'relative_strength': d['sector'],
                    'money_flow': '...',
                    'leader_follower': '...',
                    'catalyst': '...',
                    'risk': d['risk']
                }

# 5. 同步更新 today_snapshot
watchlist['today_snapshot'] = {
    'fetch_time': '2026-06-02 23:50 CST',
    'source': '收盘监控复盘_2026-06-02',
    'market_summary': '...',
    'stocks_with_data': [...],
    'overall_action': '...'
}

# 6. 保存（保留原有格式和注释会被清除，这是 trade-off）
with open('config/stock_monitor/watchlist.yaml', 'w') as f:
    yaml.dump(watchlist, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

# 7. 验证
yaml.safe_load(open('config/stock_monitor/watchlist.yaml'))
```

**关键校验点**：
- `code + name` 双重匹配，防止同一 code 不同 name 的票被误更新
- 遍历后打印更新计数，确认与预期票数一致
- 同一票在多个 theme 中会自动全部更新（因为遍历的是 theme → stocks 嵌套结构）

**Trade-off**：`yaml.dump` 会清除 YAML 中的注释和自定义格式。如果文件中有重要注释，先用 `git diff` 确认变更范围是否合理。

### 数据已同步的识别与处理
- **症状**：执行更新前发现 watchlist 的 `today_snapshot`、`technical_narrative`、`sector_narrative` 已包含复盘文档中的数据。
- **根因**：用户可能已手动更新，或前一次会话已执行过同步。
- **处理原则**：
  1. 不要重复写入相同数据。
  2. 通过 `yaml.safe_load()` 读取并比对关键字段（`trend`、`note`、`relative_strength`、`market_summary`）确认是否已同步。
  3. 若已同步，向用户报告当前状态（各票 narrative 摘要、today_snapshot 数据点），并询问是否需要基于**今早动态**追加更新（如新增 sector_group、调整 up_mention_status）。
  4. 若部分同步（如 today_snapshot 已更新但某票的 sector_narrative 缺失），仅补全缺失部分。

### 验证清单
- [ ] `git pull` 完成，无冲突
- [ ] **UP "关注方向"已提取**：复盘文档中"关注地位方向""核心思路"等段落的标的已检查并处理（新增或更新 watch_reason）
- [ ] 所有复盘文档中提到的票都已更新 narrative
- [ ] 同一票在多个 theme 中的每个位置都已更新
- [ ] 同一 code 不同 name 的票已按 `code+name+role` 区分，无错位
- [ ] `yaml.safe_load()` 验证通过，无解析错误
- [ ] `today_snapshot` 中的市场数据与复盘文档一致
- [ ] `git diff --stat` 确认变更范围合理
- [ ] **数据重复检查**：确认不是对已同步数据的重复写入
- [ ] **用户验证**：提示用户通过 SSH 检查文件，提供具体路径和变更摘要

## 用户交互规范

执行本流程时遵守以下用户偏好：
- **简洁优先**：用户偏好简短回复，不喜欢过度解释。给出变更摘要即可，无需逐步说明每个操作。
- **"停"信号**：用户说"停"/"stop"/"不要改"/"don't change"时，立即停止当前操作，不完成剩余步骤。
- **先文档后脚本**：当用户同时要求"补充到文档"和"改脚本"时，优先完成文档更新，脚本修复延后。
- **减少逻辑**：用户明确拒绝区分逻辑时（如"不用区分置顶评论和普通评论，只看用户名"），立即按简化方案执行。
- **数据已同步时**：若发现 watchlist 已包含复盘文档数据，不要重复写入。向用户报告当前同步状态，并询问是否需要基于**今早动态**追加更新。
- **账户命名灵活性**：用户可能使用任意账户名称（如"大同账号""华宝账号"而非"账号1""账号2"）。更新 `positions.yaml` 时以用户提供的名称为准，不强制使用固定命名。若用户要求重命名账户，同步更新 `positions.yaml` 中所有引用该账户名的地方（包括 `account` 字段和 `strategy_summary` 中的描述）。
- **LLM 幻觉识别**：当用户指出 cron 任务报告中的数据错误（如"万通发展没有涨停"），按 `references/llm-hallucination-prevention.md` 中的流程处理：验证 state.json/实时行情 → 标记幻觉 → 更新 prompt 约束。
- **持仓更新完整流程**：用户要求"更新持仓"时，执行完整 pipeline：获取实时行情 → 计算 PnL → 交叉引用 claims → 验证 watchlist.yaml → 更新 `positions.yaml` 的 `today_snapshot` + 持仓记录 + `strategy_summary`。不能只改持仓股数而忽略市场上下文和可操作建议。
- **提交前 git status**：执行 `git status --short` 和 `git diff --stat` 确认变更范围，再 `git add -A && git commit && git push`。

## 禁止事项

- 不编造价格、财务、新闻或博主观点。
- 不把推断伪装成 UP 原话。
- 不删除旧 theme，除非用户明确说移除。
- 不跳过验证直接提交。
- 不将单日语境直接提升为长期 framework。
