# 指数多级别K线 + MACD/九转/斐波那契 数据层

> 支持 Qing-Agent 按 UP 方法论做多时间维度顶底结构判断的数据基础设施。
> 最后更新：2026-06-12 (v2 — 新增§使用边界 + 数据流架构 + prompt文件链接)

---

## ⚠️ 使用边界（2026-06-12 用户纠正，必须遵守）

**MACD/九转/斐波那契数据只用于大盘（全A指数000985 + 上证指数000001）顶底判断，不得用于个股分析。**

| 分析目标 | 允许使用的指标 | 禁止使用的指标 |
|----------|---------------|---------------|
| **大盘**（全A/上证顶底结构） | MACD多级别背离/金叉/死叉 | — |
| | 神奇九转高9/低9（辅助判断） | — |
| | 斐波那契时间窗口（辅助判断） | — |
| **个股**（持仓/观察池） | 成交量、换手率、支撑位、压力位 | ❌ MACD |
| | K线形态、分时图 | ❌ 九转序列 |
| | 板块联动、资金流向 | ❌ 斐波那契 |

**输出格式要求**：
- MACD/九转/斐波那契分析结果**不独立成段**（如单独的【MACD结构】标题）
- 必须融入大盘判断的综合结论中（如【综合判断】或【盘面】段落）
- 例如：`"60分钟底背离+日线低9+21天斐波那契窗口共振→底部区域确认"` 写在盘面分析里，不另起标题

**Prompt 层约束**（修改提示词时须同步更新）：
- `prompts/system/market_analysis_framework.txt` Step 2 — 每条规则标注「仅用于大盘」
- `prompts/system/stock_analyst.txt` 技术位置分析 — 明确禁止MACD，个股用成交量/换手率/支撑/压力/K线
- 技术设计文档：`docs/qing-agent-technical-design.md` §4.6

---

## 数据管线架构

```
东方财富 API (push2.eastmoney.com)
  klt=30/60/120/101, secid=1.000001(上证)/1.000985(全A)
    │
    ├── 06:30 预拉取 (qing_pre_fetch_klines.py, cron)
    │     全量拉取160根/指数/周期, 计算MACD, 合成90min
    │
    └── 每30min 盘中增量 (update_index_klines_intraday.py, cron)
          只在 09:15-15:15 交易时段执行
          INSERT OR REPLACE 去重
          no_agent=true + deliver=local (0 token, 不推送)
    │
    ▼
SQLite: infra/data/kline_cache.db → index_klines 表
  (code, timeframe, bar_time, O/H/L/C, volume, dif, dea, macd_hist)
  2指数 × 5周期 × ~160根 = 2,428+ 条, 748KB
    │
    ▼
kline_cache.py (读取层)
  │
  ├── format_multi_tf_macd_report()     → 精简MACD快照(536字符)
  │     默认只处理 sh000001 + sh000985 (不加深证/创业板)
  │     输出: 上证一行 + 全A一行, 日线60min详
  │
  ├── calculate_td_sequential_multi_tf() → TD9报告
  │     5周期高9/低9检测
  │
  └── calculate_fibonacci_time_window() → 斐波那契时间窗口
        距8/13/21/34/55交易日对照
    │
    ▼
graph/nodes.py (market_analyst 节点)
  注入 AgentState 三个字段:
    macd_multi_tf_report   → Agent 大盘分析 Step 2
    td_sequential_report   → Agent 大盘分析 Step 2
    fibonacci_time_report  → Agent 大盘分析 Step 2
    │
    ▼
Prompt 层 (LLM 使用约束)
  market_analysis_framework.txt (Step 2: 大盘顶底规则 + 使用边界)
  stock_analyst.txt            (个股: 明确禁令)
```

## 90分钟数据合成

东方财富不支持原生 `klt=90`，由3根30分钟K线合成：
- O = 第一根的开盘
- H = 三根的最高
- L = 三根的最低
- C = 最后一根的收盘
- V = 三根成交量之和
- MACD = 用最后一根30分钟K线的DIF/DEA/MACD柱

## 每日更新时序

| 时间 | 动作 | 说明 |
|------|------|------|
| 06:30 | 预拉取（全量） | 拉取5指数×4时间级别×~160根K线，重算MACD |
| 09:15-15:00 | 盘中增量（每30分钟） | 只拉最新数据，INSERT OR REPLACE 幂等 |
| 非交易时段 | 静默 | `is_trading_time()` 检查跳过 |

---

## ⚠️ Prompt 工程教训：MACD 显示的三次迭代（2026-06-12）

### 迭代过程

| 版本 | Prompt 表述 | LLM 行为 | 结果 |
|------|------------|---------|------|
| v1 (初始) | 无使用边界规则 | LLM 自由发挥：MACD/九转/斐波那契作为独立段落输出 + 个股分析也用 MACD | ❌ 独立段落，个股混入 MACD |
| v2 (矫枉过正) | "MACD/九转/斐波那契只用于大盘，不用于个股分析。不独立成段，融入【综合判断】中" | LLM 理解成"不要写MACD"→ 大盘分析中完全消失 | ❌ 直接丢弃 |
| **v3 (正确)** | **"不丢弃，只合并。大盘分析必须体现MACD/九转/斐波那契的判断结论（如'日线绿柱缩短'），只是不单独成段，不是丢弃"** | 盘面段落中包含 MACD 结构判断，个股则完全使用量能/换手率/支撑/压力 | ✅ 正确 |

### 教训（prompt 工程师必读）

1. **"融入XX"太模糊**：LLM 不知道如何"融入"→ 干脆不写。需要给出具体例子（`market_summary` 写为"全A弱修复，60分钟底背离中+日线低9已兑现"）
2. **"只用于大盘"LLM 可能理解为"别用"**：需要明确"必须体现"而不是"只能用"
3. **不独立成段 ≠ 丢弃**：需要用"不丢弃，只合并"这样的短语消除歧义
4. **边界必须精确**：
   - 大盘分析：必须回答 MACD 结构（底背离/金叉？）、九转计数（高9/低9？）、斐波那契窗口（到位了吗？）
   - 个股分析：一个字都不要提 MACD——用 成交量/换手率/支撑位/压力位/K线形态/分时图
5. **关键短语**："只用于大盘"+"不丢弃只合并"+"必须体现"+"不单独成段"
6. **三步共振法（v3 第二次修正）**：数据不能只罗列，必须合成结论：
   ```
   第1步：找共振 — MACD多级别一致？九转匹配？斐波那契到位？
   第2步：下结论 — "60分钟底背离+日线低9+21天窗口→四维共振，底部确认中"
   第3步：定操作 — 底部共振→可试错；顶部共振→减仓；分歧→多看少动
   ```
   禁止单独【MACD结构】段落，必须融入 `market_summary`。
7. **动作绑定价格（v3 第二次修正）**：个股操作必须有具体执行价格：
   ```
   "减仓"→必须写"现价减仓"或"反弹到135减仓"，默认按最新价执行
   ```

### 对应文件中的实现位置

| 规则 | 文件 | 位置 |
|------|------|------|
| 大盘分析 Step 2 + 使用边界 | `prompts/system/market_analysis_framework.txt` | Step 2 标题 + 底部"大盘顶底数据使用规则" |
| 个股分析禁止 MACD | `prompts/system/stock_analyst.txt` | 第 27-28 行 "严禁在个股分析中使用" |
| 数据注入 + 大盘分析主 prompt | `prompts/system/market_analyst.txt` | 通过 `{analysis_framework}` 占位符加载 |

---

## 关键函数

### 读取（`src/qing_investment/kline_cache.py`）

```python
from qing_investment.kline_cache import (
    get_index_klines,          # 读某指数某周期最近N根K线
    get_index_macd_snapshot,   # 所有周期 MACD 快照（含金叉/死叉/柱趋势）
    format_multi_tf_macd_report,  # 生成纯文本报告（直接喂给LLM）
    compute_td_report,         # 神奇九转序列报告
    compute_fibonacci_time_report,  # 斐波那契时间窗口报告
)

# 读最近N根K线（升序）
klines = get_index_klines("sh000001", timeframe="60min", bars=30)

# 读所有周期MACD快照
snap = get_index_macd_snapshot("sh000985")
# → {"code": "sh000985", "timeframes": {"daily": {...}, "90min": {...}, ...}}

# 生成LLM报告（含快照+明细）
report = format_multi_tf_macd_report(codes=["sh000985"], bars=10)

# 九转序列
td = compute_td_report("sh000985", "daily")  
# → "神奇九转（daily）: 当前序列 🔴高1
#     已完成信号: 2026-06-11 🟢低9  2026-05-14 🔴高9"

# 斐波那契时间窗口
fib = compute_fibonacci_time_report("sh000985")
# → "最近高点: 2026-05-13 距今22交易日 接近21(差1天)⚠️"
```

### 预拉取（`scripts/qing_pre_fetch_klines.py`）

```bash
# 全量拉取（覆盖式写入）
cd ~/learning-investment-strategies
.venv/bin/python scripts/qing_pre_fetch_klines.py --days 120

# 仅拉上证 60分钟
.venv/bin/python scripts/qing_pre_fetch_klines.py --indices sh000001 --timeframes 60min

# 仅测试不写DB
.venv/bin/python scripts/qing_pre_fetch_klines.py --dry-run
```

### 盘中增量更新（`scripts/update_index_klines_intraday.py`）

```bash
# 幂等更新（非交易时段跳过）
.venv/bin/python scripts/update_index_klines_intraday.py

# 强制执行（跳过交易时段检查）
.venv/bin/python scripts/update_index_klines_intraday.py --force

# 仅测试不写DB
.venv/bin/python scripts/update_index_klines_intraday.py --dry-run
```

---

## Cron Job

```yaml
# 盘中每30分钟增量更新（no_agent模式，无LLM调用，无微信通知）
job_id: a9bdc762b20e
name: 指数K线盘中增量更新（30分钟）
schedule: "*/30 9-15 * * 1-5"
script: update_index_klines_intraday.sh   # ~/.hermes/scripts/下
no_agent: true
deliver: local
workdir: /home/ubuntu/learning-investment-strategies
```

**数据采集 cron 必须使用 `no_agent=true` + `deliver=local`**：纯脚本执行，0 token 消耗，不推送通知。只有生成分析结果的 cron（如尾盘条件单）才使用 LLM 驱动模式。

---

## Agent 集成（`nodes.py` `market_analyst` 节点）

Agent 在 `market_analyst` 运行时自动注入三个数据源：

| 字段 | 来源函数 | 用途 |
|------|---------|------|
| `macd_multi_tf_report` | `format_multi_tf_macd_report()` | MACD 顶底背离判断 |
| `td_sequential_report` | `compute_td_report()` | 神奇九转高9/低9信号 |
| `fibonacci_time_report` | `compute_fibonacci_time_report()` | 斐波那契时间窗口 |

对应的 prompt 规则在以下文件中，修改提示词时须同步更新：

| 文件 | 角色 |
|------|------|
| `prompts/system/market_analysis_framework.txt` | Step 2 大盘顶底规则 + 使用边界（仅用于大盘，不独立成段） |
| `prompts/system/stock_analyst.txt` | 个股技术分析禁用MACD |
| `docs/qing-agent-technical-design.md` §4.6 | 完整技术架构文档 |

---

## 仅覆盖两个指数

`format_multi_tf_macd_report()` 默认只处理 `sh000001`(上证指数) 和 `sh000985`(中证全指)。**深证成指和创业板指不做多级别MACD分析**。

---

## MACD 预热期

MACD 需要足够历史才能稳定。每个周期的有效起始：
- `ema(26)` 需要 26 根 → DIF 从第 27 根开始有效
- `ema(dif, 9)` 需要再加 9 根 → DEA/MACD柱从第 36 根开始有效

所以日线 160 根中 ~127 根有完整 MACD，30分钟 255 根中 ~222 根有完整 MACD。

---

## ⚠️ 关键陷阱：API 数据顺序

**东方财富 API 返回的 K 线顺序不稳定**（有时升序有时降序），**禁止 `reverse()`**。必须显式排序：

```python
# ✅ 正确
result.sort(key=lambda k: k["bar_time"])  # 显式排序

# ❌ 错误（导致 MACD 在反向数据上计算，最新数据 DIF=NULL）
result.reverse()
```

**错误后果**：如果数据是新→旧顺序存入，MACD 会在反向数据上计算。前 26 根（最新 26 根）的 DIF=NULL，Agent 看不到最近的顶底结构信号。症状：DB 中最近日期的 DIF/dea 全部为 NULL，但更早日期正常。

**排查命令**：
```sql
-- 检查数据是否升序
SELECT MIN(bar_time), MAX(bar_time) FROM index_klines WHERE code='sh000001' AND timeframe='daily';
-- 如果 MIN > MAX → 数据是降序的 → BUG
```

---

## 当前 MACD 状态示例（2026-06-12 中证全指）

| 级别 | DIF | DEA | 柱 | 趋势 | 含义 |
|------|-----|-----|-----|------|------|
| 日线 | -51.8 | -16.2 | -71.2 | 绿柱缩短 | 大级别下跌动能减弱 |
| 120min | -67.3 | -66.3 | -2.1 | 绿柱缩短 | 濒临金叉 |
| 60min | -31.0 | -46.7 | +31.3 | 红柱放大 | 底部金叉→反弹进行中 |
| 30min | +6.3 | -5.9 | +24.3 | 红柱缩短 | 小级别反弹近尾声 |
