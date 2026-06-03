# 从复盘文档批量更新 narrative 的参考手册

> 当用户要求"把复盘文档的市场数据提取到 watchlist 对应票的 technical_narrative 和 sector_narrative"时的执行参考。

---

## 数据提取清单（从复盘文档）

### 必须提取的数据

| 数据类型 | 来源位置 | 示例 |
|---------|---------|------|
| 指数收盘 | "附：今日关键数据速查"表或开头大盘段落 | 上证 4075.1(+0.43%) |
| 板块表现 | "今日盘面主线"或"热点板块表现" | CPO领涨，MLCC/PCB同一节奏 |
| 个股数据 | "附：今日关键数据速查"表 | 万通发展 15.83(-2.10%) |
| 持仓盈亏 | "漏报检查"中的持仓表或持仓段落 | 万通发展浮亏-2.3% |
| **UP 关注方向** | **"关注地位方向""核心思路""方向提示"等明确段落** | **鼎龙股份（光刻胶/CMP国产第一）、裕太微（以太网PHY）** |
| 板块强弱 | "误导性提醒"中的进攻组均涨幅 | 11:00 进攻组均涨幅 -1.246% |

### 可选提取的数据

- 去重合理性：被去重压制信号数（用于判断是否需要调整去重窗口）
- 漏报原因：positions.yaml 配置缺失、sector_groups 滞后、cron 执行失败
- 下一交易日观察条件：3条核心观察条件
- 研报核心：UP 提到的行业研报要点（感光干膜、镁合金等）
- 强势股/新增催化：英伟达点名方向、涨停个股及逻辑

---

## 关键区分：两种更新模式

当用户要求"把复盘文档提取到 watchlist"时，必须区分两种模式，**不可只做模式 A 而遗漏模式 B**：

### 模式 A：更新已有票的 narrative（基础）
- 扫描 watchlist 中已有的票
- 更新 `technical_narrative` + `sector_narrative`
- 更新 `today_snapshot`

### 模式 B：提取 UP 新提到的"关注方向"（极易遗漏）
- **必须扫描复盘文档中的"关注地位方向""核心思路""方向提示"等段落**
- 提取 UP 明确提示要关注的标的（即使当前不在 watchlist 中）
- 检查这些标的是否已在 watchlist 中：
  - **若不存在**：新增 theme 或追加到对应 theme，写入完整字段（含 narrative）
  - **若已存在**：更新 narrative，并在 `watch_reason` 中追加 UP 最新提示

**常见遗漏**：UP 在复盘中明确说"关注地位方向：鼎龙股份、裕太微、工业富联..."，但 agent 只更新了已有持仓票的 narrative，完全遗漏这些新方向。

**正确做法**：先执行模式 A（已有票更新），再执行模式 B（新方向提取），两步都完成后才算完整。

---

## narrative 字段内容模板

### technical_narrative

```yaml
technical_narrative:
  trend: "{日期}{涨跌幅}{定性描述}"
  volume_character: "{放量/缩量/正常成交}{上涨/下跌/震荡}"
  key_levels:
  - "支撑：{价格}"
  - "压力：{价格}"
  pattern: "{技术形态}"
  note: "{日期}收盘{价格}{关键状态}，{板块context}"
```

**内容规范**：
- `trend` 必须包含具体日期和涨跌幅数字
- `note` 必须包含收盘价，持仓票必须包含成本线和盈亏比例
- `key_levels` 中的支撑/压力必须基于当日高低点和近期平台

### sector_narrative

```yaml
sector_narrative:
  relative_strength: "{板块组内位置}"
  money_flow: "{主力/游资/稳健资金}{流入/流出}"
  leader_follower: "{板块龙头/跟随/独立走势}"
  catalyst: "{催化事件}"
  risk: "{具体风险描述}"
```

**内容规范**：
- `relative_strength` 必须包含该票在所属板块组内的相对位置
- `risk` 必须包含当日观察到的具体风险，不能写泛泛的"市场风险"
- `money_flow` 基于当日成交量变化和板块资金流向判断

---

## 推荐更新方式：Python 批量更新（优于 Patch）

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

---

## 常见错误与修复

### 错误 1：换行缺失导致 YAML 解析失败

**症状**：`yaml.safe_load()` 返回 `technical_narrative: None`

**根因**：
```yaml
    invalidation_setup:
    - AI电源链整体走弱    technical_narrative:  # ← 缺少换行
```

**修复**：
```yaml
    invalidation_setup:
    - AI电源链整体走弱
    technical_narrative:  # ← 正确：有换行
```

### 错误 2：只更新了票的一个 theme 位置

**症状**：同一票在 `upstream_price_increase` 中更新了，但在 `mlcc_passive_cycle` 中仍是旧数据

**根因**：只按 `code` 匹配，未检查该票在哪些 theme 中出现

**修复**：先用 `grep -n "code: 000636.SZ"` 找出所有出现位置，逐一更新。或直接用 Python 批量遍历（见上方推荐方式）。

### 错误 3：today_snapshot 数据与复盘文档不一致

**症状**：`today_snapshot.market_summary` 中的指数数据与复盘文档不同

**根因**：只更新了 narrative，忘记同步更新 today_snapshot

**修复**：将 today_snapshot 中的 market_summary、stocks_with_data、overall_action 全部用复盘文档数据重写

### 错误 4：只更新了 watchlist，未同步更新 strategy_pack 的 entry_points

**症状**：watchlist 的 narrative 已更新，但 strategy_pack 中没有对应的介入策略，观察池无法指导交易

**根因**：只执行了模式 A（已有票 narrative 更新），遗漏了模式 B（新方向提取）和 strategy_pack 同步

**修复**：每次更新 watchlist 后，必须检查：
1. 复盘中是否有"关注地位方向"等新标的 → 加入 watchlist
2. 所有重点标的是否在 strategy_pack 的 entry_points 中有操作策略
3. entry_zone 是否为具体价格数字，而非模糊描述

### 错误 5：编造价格数据

**症状**：entry_zone 写了"26.5-27.5"等具体数字，但实际数据源降级无法获取价格

**根因**：为了回应用户"介入股价区间呢？"的压力，编造了虚假价格

**修复**：
- 数据源降级时诚实说明："无法获取实时价格，需手动填写"
- 提供计算规则："基于当日收盘价，回踩 5-7% 介入"
- **绝不编造价格**——用户会验证，信任一旦崩塌难以修复

---

## 用户验证习惯（重要）

**用户不信任 AI 对文件位置的声明**，会通过 SSH 登录服务器直接检查文件。执行写入操作后：
1. 主动提供文件的绝对路径和关键内容摘要
2. 建议用户运行 `ls -la <路径>` 和 `git diff --stat` 自行验证
3. 不要假设用户会信任"已写入"的声明

---

## 必须同步更新 strategy_pack.yaml（不可遗漏）

当用户要求"把复盘文档提取到 watchlist"时，**只更新 watchlist.yaml 是不够的**。必须同时更新 `strategy_pack.yaml` 的 `quant_entry_strategy.entry_points`：

### 为什么必须同步更新 strategy_pack

- watchlist 的 `technical_narrative` + `sector_narrative` 描述的是**当前状态**
- strategy_pack 的 `entry_points` 描述的是**明日可执行的操作策略**（介入区间、仓位、触发条件、失效条件）
- **没有 entry_points = 观察池只是摆设，无法指导实际交易**

### entry_points 字段规范

```yaml
entry_points:
- code: "300054.SZ"
  name: "鼎龙股份"
  priority: 4
  sector: "光刻胶/CMP国产替代"
  close: 28.5          # 当日收盘价（从数据获取脚本读取）
  change_pct: 2.1      # 当日涨跌幅
  assessment: "UP明确提示关注地位方向：高端光刻胶/CMP国产替代第一..."
  trigger_buy:
  - "半导体板块整体企稳"
  - "光刻胶/CMP国产替代逻辑被市场认可"
  - "不追高，等缩量回踩"
  entry_zone: "26.5-27.5"   # ← 必须提供具体价格区间，不能写"近期平台附近"
  position_ratio: "1成"      # ← 必须提供具体仓位
  invalidation:
  - "半导体业绩证伪"
  - "国产替代进度不及预期"
```

**entry_zone 填写规范**：
- **必须提供具体价格数字**，不能写"近期平台附近""等分歧后缩量回踩"等模糊描述
- 若数据源可用：基于当日收盘价，回踩 5-7% 计算（如收盘 28.5 → 介入区间 26.5-27.5）
- 若数据源降级无法获取实时价格：
  - **诚实说明**："数据源降级，无法获取实时价格。需手动填写"
  - **提供计算规则**："基于当日收盘价，回踩 5-7% 介入"
  - **绝不编造虚假价格**（用户会验证，编造价格会导致信任崩塌）
- 对于已大涨的票（如单日 +18%）：介入区间需等更充分调整（10-15%）

**position_ratio 填写规范**：
- 必须提供具体仓位（如"1成""0.5成"）
- 高弹性/高风险票降低仓位（如裕太微 0.5 成）
- 空仓总仓位控制在 6 成以内（因新增多个方向）

**无持仓票不配置 stop_loss**：
- 用户明确："没有持仓的不用止损，主要是介入区间和操作策略"
- `stop_loss` 字段只用于已有持仓的票
- 观察池新票只配置 `entry_zone` + `invalidation`（失效条件）

### 更新顺序

1. 更新 watchlist.yaml（narrative + today_snapshot）
2. **同步更新 strategy_pack.yaml**（entry_points + position_advice）
3. 更新 positions.yaml（持仓 PnL + today_plan）
4. 三步全部完成后才算完整

---

## 常见遗漏：UP "关注地位方向"的新标的

当复盘中出现"关注地位方向""核心思路""方向提示"等段落时，**必须提取其中提到的所有标的**：

1. 检查这些标的是否已在 watchlist 中
2. 若不存在：新增 theme 或追加到对应 theme
3. 无论是否新增：都必须在 strategy_pack.yaml 的 `entry_points` 中补充操作策略

**典型遗漏案例**：
- 复盘提到"关注地位方向：鼎龙股份（光刻胶）、裕太微（以太网PHY）、工业富联（CPO交换机）"
- Agent 只更新了已有票的 narrative，完全遗漏这 3 只新标的
- 正确做法：新增 theme "关注地位方向_YYYYMMDD"，写入完整字段，并在 strategy_pack 中补充 entry_points

---

## 快速验证命令

```bash
# 验证 YAML 格式
cd ~/learning-investment-strategies
python3 -c "import yaml; yaml.safe_load(open('config/stock_monitor/watchlist.yaml'))"
python3 -c "import yaml; yaml.safe_load(open('config/stock_monitor/strategy_pack.yaml'))"

# 检查特定票的 narrative
grep -A 20 "code: 600246.SH" config/stock_monitor/watchlist.yaml | grep -E "trend:|relative_strength:"

# 检查 today_snapshot 数据
grep -A 5 "market_summary:" config/stock_monitor/watchlist.yaml

# 检查 entry_points 是否包含新标的
grep -A 5 "entry_zone:" config/stock_monitor/strategy_pack.yaml | head -30

# 用户自助验证（推荐提示用户执行）
ls -la config/stock_monitor/watchlist.yaml
git diff --stat config/stock_monitor/
```
