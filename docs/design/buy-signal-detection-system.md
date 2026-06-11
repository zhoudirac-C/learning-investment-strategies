# 买入信号自动检测系统 — 设计文档

> 版本: v1.0 | 日期: 2026-06-11 | 作者: Hermes + UP 方法论
>
> 目标：让系统像 UP 一样思考——观察池标的满足条件时，自动给出确定性的买入/不买信号，不再"永远在等"。

---

## 一、问题陈述

### 1.1 现状断层

```
当前：cron 定时 → Qing-Agent 全量分析 → 输出"等缩量企稳" → 用户自己盯盘
目标：cron 轮询 → poll 检测条件 → Agent 单票确认 → 输出"买，现价X，止损Y"
```

### 1.2 根因

| 环节 | 现状 | 问题 |
|------|------|------|
| **触发机制** | 纯定时（9:26/9:45/10:00/...） | 条件满足了没触发，时间到了瞎分析 |
| **检测粒度** | 仅价格区间（add_zone） | 不做量价配合判断，缺了 UP 最核心的"缩量→放量转折"识别 |
| **Agent 模式** | 全量 market 分析 | 一次分析所有标的→每只票只能得到一句话，无法深度研判 |
| **输出格式** | "可买：等缩量企稳" | 永远在"等"，用户误以为是买入信号（如 6/11 中化国际涨停） |

### 1.3 用户真实需求

> "大模型替我盯盘，观察池里的票缩量企稳了，告诉我今天这个点位可以买入。"
> "做到和 UP 同样的思维逻辑，分析之后，直接给我买入信号。"

---

## 二、公开设计参考

### 2.1 业界常见模式

以下模式来自公开的量化交易系统设计（Zipline、Backtrader、vnpy、Freqtrade 等开源项目），不涉及具体实现，仅提取架构模式：

**模式 A：信号管线（Signal Pipeline）**
```
行情数据 → 信号检测器1..N → 信号聚合 → 仓位管理器 → 订单执行
```
- 代表项目：Zipline（Quantopian）、Backtrader
- 核心思想：每个信号检测器是独立的 filter，产出标准化的 Signal 对象
- **可借鉴**：信号标准化（Signal dataclass），多检测器并行

**模式 B：条件单引擎（Condition Order Engine）**
```
实时行情 → 条件评估器 → 触发 → 指令生成 → 通知
```
- 代表项目：vnpy（CTA 策略引擎）
- 核心思想：每个标的维护一个条件状态机（等待→条件满足→触发），不是每次全量扫描
- **可借鉴**：状态机管理每个标的的买入条件生命周期

**模式 C：LLM Agent 确认层（Agent-in-the-Loop）**
```
规则引擎触发 → LLM Agent 确认 → 最终信号
```
- 代表设计：LLM 辅助量化（2024-2025 年兴起的范式）
- 核心思想：规则引擎负责初筛（高速、确定性），Agent 负责深度研判（低速、模糊判断）
- **可借鉴**：两级决策架构——规则做初筛减负，Agent 做确认不遗漏

**模式 D：事件驱动架构（Event-Driven）**
```
行情更新事件 → 事件总线 → 感兴趣的条件监听器 → 条件满足 → 触发分析
```
- 代表设计：Freqtrade、Jesse
- 核心思想：不轮询全部标的，而是行情变化时推送给订阅了该标的的条件监听器
- **可借鉴**：按标的订阅条件，避免全量扫描

### 2.2 本项目选型

结合以上模式和现有基础设施（5分钟轮询 cron + Qing-Agent + 微信推送），选择**模式 C + D 混合**：

```
行情轮询(5min) → 条件状态机(每标的) → 初筛命中 → Agent 单票确认 → 微信推送
   ↑ 已有                 ↑ 新增              ↑ 新增      ↑ 改造         ↑ 已有
```

选择理由：
1. **不引入事件总线**：当前是 cron 轮询架构，引入实时事件总线改动太大。5分钟轮询在 A 股 T+1 环境下足够（不需要高频决策）
2. **两级决策合理**：规则做初筛（量价计算是确定性的），Agent 做确认（板块联动、大盘环境需要推理）
3. **最小改动**：复用 poll cron job → 新增买入信号检测函数 → 复用 Agent HTTP API → 复用微信推送

---

## 三、系统架构

### 3.1 整体数据流

```
┌─────────────────────────────────────────────────────────────┐
│  cron: qing_stock_monitor_poll.py (每5分钟，no_agent)       │
│                                                             │
│  1. 拉取行情（东方财富 API）                                  │
│  2. 加载 watchlist.yaml 中的 entry_zone 配置                 │
│  3. 对每个 watchlist 标的执行买入信号检测                      │
│     ├── 3a. 价格区间检测（已有：add_zone）                    │
│     ├── 3b. 量价配合检测（新增）                              │
│     │      ├── 缩量止跌：近3日成交量递减 + 最低价不再创新低     │
│     │      ├── 放量阳线确认：当日量>5日均量×1.5 + 阳线         │
│     │      ├── 均线支撑：收盘价>MA20 + MA5穿越MA10向上          │
│     │      └── 不追板：当日涨幅<7%（非涨停）                    │
│     └── 3c. 综合判定（新增）                                  │
│            ├── 全部条件满足 → 触发 Agent 单票分析              │
│            ├── 部分满足→ 推送「条件进度」提醒                  │
│            └── 不满足 → 静默                                  │
│  4. 输出 RuleAlert（含 buy_signal 类型）                     │
│  5. 推送结果到微信                                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ 触发 Agent 分析
┌─────────────────────────────────────────────────────────────┐
│  cron: qing_stock_monitor_agent.py（按需触发）               │
│                                                             │
│  6. poll 输出包含 trigger_type="buy_signal_single_stock"    │
│  7. Agent 收到触发 → 加载单票上下文                           │
│     ├── K线数据（20日）                                       │
│     ├── 板块联动状态                                          │
│     ├── 大盘环境（全A指数涨跌+量能）                           │
│     └── UP 相关 claims（通过 MCP Qdrant 检索）                │
│  8. Agent 输出二值化结论                                     │
│     ├── ✅ 买入：现价/介入区间/止损/理由/风险                  │
│     └── ❌ 不买：原因（具体到不满足哪个条件）                   │
│  9. 推送到微信                                               │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 组件职责

| 组件 | 位置 | 职责 | 状态 |
|------|------|------|------|
| 行情拉取 | `stock_monitor.py::fetch_quotes_eastmoney()` | 拉取 watchlist 全部行情 | ✅ 已有 |
| 价格区间检测 | `stock_monitor.py::evaluate_position_alerts()` | add_zone 进入检测 | ✅ 已有 |
| 量价配合检测 | `stock_monitor.py::evaluate_buy_signals()` | 缩量止跌/放量阳线/均线支撑/不追板 | 🆕 设计 |
| 条件状态机 | `stock_monitor.py::BuySignalState` | 每标的维护条件满足进度 | 🆕 设计 |
| 去重/推送 | `stock_monitor.py::filter_new_alerts()` | 同一天同一标的同一信号不重复推 | ✅ 已有 |
| Agent 触发 | `stock_monitor.py::find_agent_analysis_trigger()` | 信号事件触发 Agent 分析 | 🔧 改造 |
| Agent 分析 | Qing-Agent `/analyze/trigger` | 单票深度研判 + 二值化输出 | 🔧 改造 |

---

## 四、信号定义

### 4.1 买入信号类型

```python
@dataclass
class BuySignal:
    """买入信号检测结果"""
    stock_code: str
    stock_name: str
    price: float
    signal_type: str  # "buy_ready" | "progress" | "not_ready"
    
    # 三级条件
    price_in_zone: bool        # 价格进入介入区间
    volume_shrinking: bool     # 缩量止跌
    volume_breakout: bool      # 放量阳线确认
    ma_support: bool           # 均线支撑
    no_limit_up: bool          # 非涨停板（不追板）
    
    # 综合
    all_conditions_met: bool   # 全部满足 → 触发 Agent
    partial_conditions: list[str]  # 部分满足的条件名
    
    # 上下文
    entry_zone: tuple[float, float]
    stop_loss: float
    confirm_signal: str
```

### 4.2 检测算法

#### 4.2.1 缩量止跌检测

```python
def detect_volume_shrinking(kline_data: list[dict]) -> bool:
    """
    条件：
    1. 近3日成交量递减（vol_d1 < vol_d2 < vol_d3，d1为最近）
    2. 近3日最低价不再创新低（low_d1 >= min(low_d2, low_d3)）
    """
    if len(kline_data) < 4:
        return False
    
    d1, d2, d3 = kline_data[-1], kline_data[-2], kline_data[-3]
    
    vol_shrink = d1['volume'] < d2['volume'] < d3['volume']
    low_stable = d1['low'] >= min(d2['low'], d3['low'])
    
    return vol_shrink and low_stable
```

#### 4.2.2 放量阳线确认

```python
def detect_volume_breakout(kline_data: list[dict]) -> bool:
    """
    条件：
    1. 当日量 > 5日均量 × 1.5
    2. 当日阳线（收盘 > 开盘）
    3. 收盘 > 昨日收盘（确认不是在跌）
    """
    if len(kline_data) < 6:
        return False
    
    today = kline_data[-1]
    yesterday = kline_data[-2]
    vol_5d_avg = sum(d['volume'] for d in kline_data[-6:-1]) / 5
    
    vol_break = today['volume'] > vol_5d_avg * 1.5
    is_yang = today['close'] > today['open']
    price_up = today['close'] > yesterday['close']
    
    return vol_break and is_yang and price_up
```

#### 4.2.3 均线支撑检测

```python
def detect_ma_support(kline_data: list[dict]) -> bool:
    """
    条件：
    1. 收盘价 > MA20（在20日线上方）
    2. MA5 上穿 MA10（短期趋势转强）
    或
    1. 收盘价 > MA20
    2. 收盘价 > MA5（强势票）
    """
    if len(kline_data) < 21:
        return False
    
    closes = [d['close'] for d in kline_data]
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    
    above_ma20 = closes[-1] > ma20
    
    # 方案A：MA5上穿MA10（稳健信号）
    prev_ma5 = sum(closes[-6:-1]) / 5
    prev_ma10 = sum(closes[-11:-1]) / 10
    golden_cross = prev_ma5 <= prev_ma10 and ma5 > ma10
    
    # 方案B：强势票（收盘在MA5上方）
    above_ma5 = closes[-1] > ma5
    
    return above_ma20 and (golden_cross or above_ma5)
```

#### 4.2.4 不追板检测

```python
def detect_no_limit_up(quote: dict) -> bool:
    """当日涨幅 < 7%（非涨停，也不接近涨停）"""
    pct_change = float(quote.get('pct_change', 0))
    return pct_change < 7.0
```

#### 4.2.5 综合判定：买入准备就绪

```python
def evaluate_buy_signal(
    quote: dict,
    kline_data: list[dict],
    entry_zone: dict,
) -> BuySignal:
    """综合判定：所有条件满足 = 买入信号准备就绪"""
    price = float(quote.get('latest', 0))
    zone_low, zone_high = parse_entry_zone(entry_zone)
    
    signal = BuySignal(
        stock_code=quote.get('code', ''),
        stock_name=quote.get('name', ''),
        price=price,
        signal_type="not_ready",
        price_in_zone=(zone_low <= price <= zone_high),
        volume_shrinking=detect_volume_shrinking(kline_data),
        volume_breakout=detect_volume_breakout(kline_data),
        ma_support=detect_ma_support(kline_data),
        no_limit_up=detect_no_limit_up(quote),
        all_conditions_met=False,
        partial_conditions=[],
        entry_zone=(zone_low, zone_high),
        stop_loss=parse_stop_loss(entry_zone),
        confirm_signal=entry_zone.get('confirm_signal', ''),
    )
    
    # 收集满足的条件
    conditions = {
        '价格在介入区间': signal.price_in_zone,
        '缩量止跌': signal.volume_shrinking,
        '放量阳线确认': signal.volume_breakout,
        '均线支撑': signal.ma_support,
        '非涨停板': signal.no_limit_up,
    }
    signal.partial_conditions = [k for k, v in conditions.items() if v]
    
    # 全部满足 → 买入准备就绪
    if all(conditions.values()):
        signal.signal_type = "buy_ready"
        signal.all_conditions_met = True
    elif len(signal.partial_conditions) >= 3:
        signal.signal_type = "progress"  # 差1-2个条件
    
    return signal
```

### 4.3 条件状态机

每个标的维护一个状态机，避免"瞬间满足又消失"的抖动：

```
                    ┌──────────┐
        价格未进入    │  IDLE    │  全部条件不满足
       ──────────────│  空闲     │────────────────
                     └────┬─────┘
                          │ 价格进入介入区间
                          ▼
                    ┌──────────┐
     部分条件满足    │WATCHING  │  缩量止跌+均线支撑满足
       ──────────────│  观察中   │────────────────
                     └────┬─────┘
                          │ 放量阳线确认满足
                          ▼
                    ┌──────────┐
    新K线否定信号    │CONFIRMING│  全部条件满足
       ──────────────│  确认中   │────────────────
                     └────┬─────┘
                          │ 去重检查通过（同一天未触发过）
                          ▼
                    ┌──────────┐
                    │TRIGGERED │  触发 Agent 分析
                    │  已触发   │
                    └──────────┘
```

**防抖机制**：
- `IDLE → WATCHING`：价格需连续 2 次轮询（10分钟）在介入区间内
- `WATCHING → CONFIRMING`：放量阳线需在当次轮询中检测到（不缓存）
- `CONFIRMING → TRIGGERED`：同一天同一标的只触发一次
- `TRIGGERED → IDLE`：次日重置

---

## 五、Agent 单票分析模式

### 5.1 API 扩展

新增 `analysis_type=single_stock` 模式：

```
POST /analyze/trigger
{
  "query": "分析 600378 昊华科技 当前是否满足买入条件",
  "session_id": "buy_signal_20260611_600378",
  "analysis_type": "single_stock",
  "stock_code": "600378",
  "stock_name": "昊华科技",
  "context": {
    "entry_zone": [51.5, 53.0],
    "stop_loss": 49.8,
    "current_price": 52.30,
    "signal_detail": {
      "price_in_zone": true,
      "volume_shrinking": true,
      "volume_breakout": true,
      "ma_support": true,
      "no_limit_up": true
    },
    "kline_summary": "近3日缩量止跌，今日放量阳线，MA5上穿MA10",
    "sector_status": "电子特气板块+2.1%，领先大盘",
    "market_status": "全A+0.8%强修复，缩量"
  }
}
```

### 5.2 Agent Prompt 约束

Agent 在 `single_stock` 模式下遵守以下约束：

```
你是青枫浦上Q风格的A股交易分析助手。当前进行【单票买入确认】分析。
规则信号已初步检测通过，你的任务是深度验证并给出二值化结论。

你需要检查：
1. 均线状态是否真正支撑（不是假突破）
2. 量价关系是否健康（放量是主动买盘还是被动反弹）
3. 板块是否联动（同板块其他标的是否同步走强）
4. 大盘环境是否允许进攻（全A不强修复则降低信心）
5. UP 相关 claim 是否有顾虑（搜索 Qdrant）

输出格式必须为以下二者之一，不得出现"等""观察""如果"等模糊词：

🟢 买入信号
代码：XXXXXX 名称
现价：XX.XX
介入区间：XX.X-XX.X
止损：XX.XX（-X.X%）
理由：（3-5条具体理由）
风险：（1-2条具体风险）

🔴 不买
代码：XXXXXX 名称
原因：（具体到不满足哪个条件，不能笼统说"条件不成熟"）
建议：（下一步什么情况下可以再关注）
```

### 5.3 二值化输出 → 微信推送

```
🟢 买入信号
雅克科技(002409) 现价119.5
介入区间：118.0-122.0 止损：112.0(-6.3%)
理由：回踩MA10获支撑+缩量止跌3日+今日放量阳线+联瑞新材同步企稳+全A缩量修复
风险：大盘若放量跌破今日低点则失效
```

---

## 六、与现有系统的集成

### 6.1 改动清单

| 文件 | 改动 | 类型 |
|------|------|------|
| `src/qing_investment/stock_monitor.py` | 新增 `evaluate_buy_signals()`、`BuySignal` dataclass、`BuySignalState` 状态机 | 新增 |
| `src/qing_investment/stock_monitor.py` | `evaluate_monitor_alerts()` 追加 buy_signal alerts | 修改 |
| `src/qing_investment/stock_monitor.py` | `format_alerts_message()` 支持 buy_signal 格式 | 修改 |
| `src/qing_investment/stock_monitor.py` | K线缓存（每次轮询拉取 watchlist 全部日K） | 新增 |
| `qing-agent` `/analyze/trigger` | 新增 `analysis_type=single_stock` 分支 + 对应 prompt | 修改 |
| `skills/qing-stock-monitor-update/SKILL.md` | 新增陷阱 24 | 文档 |

### 6.2 不新增 cron job

利用现有的 poll cron job（`qing_stock_monitor_poll.py`，每5分钟）：
- **不变**：价格区间检测、板块轮动检测、指数规则检测
- **增加**：买入信号检测（量价配合 + 综合判定）
- **增加**：买入信号触发 Agent 单票分析

### 6.3 K线数据获取

拉取东方财富日K线 API（免费、无需认证）：

```
https://push2his.eastmoney.com/api/qt/stock/kline/get?
  secid=1.600378&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61
  &klt=101&fqt=1&end=20500101&lmt=30
```

缓存策略：每5分钟轮询时拉取一次全部 watchlist 标的的日K（约20-30只），成本很低。

---

## 七、实施计划

### Phase 1: Agent 输出格式改造（1-2小时）

**目标**：解决"可买"标签误导问题

| 任务 | 内容 |
|------|------|
| 1.1 | Agent prompt 改为二值化输出（🟢买入 / 🔴不买），禁止模糊词 |
| 1.2 | 观察池标签从「✅ 可买」改为「📋 条件单待触发」|

**验收**：下次 Agent 分析输出不再出现"等""关注""如果……可以……"

### Phase 2: 买入信号检测引擎（3-4小时）

**目标**：poll 脚本能自动检测量价配合

| 任务 | 内容 |
|------|------|
| 2.1 | 实现 `BuySignal` dataclass 和四个检测函数 |
| 2.2 | 实现 K线数据缓存（拉取+存储+过期逻辑） |
| 2.3 | 实现条件状态机（防抖） |
| 2.4 | `evaluate_monitor_alerts()` 集成买入信号 |
| 2.5 | 单元测试（用历史K线验证检测逻辑） |

**验收**：poll 运行时日志中看到 `buy_ready` / `progress` 信号

### Phase 3: Agent 单票分析链路（2-3小时）

**目标**：poll 触发 → Agent 确认 → 微信推送

| 任务 | 内容 |
|------|------|
| 3.1 | Qing-Agent `/analyze/trigger` 新增 `single_stock` 模式 |
| 3.2 | Agent prompt 切换逻辑（market vs single_stock） |
| 3.3 | poll 脚本输出 buy_signal 到 cron 上下文 |
| 3.4 | 端到端测试（手动构建买入信号 → 观察推送） |

**验收**：模拟买入信号 → 微信收到 🟢买入信号 推送

### Phase 4: 全自动闭环（2-3小时）

**目标**：盘中无需人工干预

| 任务 | 内容 |
|------|------|
| 4.1 | poll 的 buy_ready 信号自动触发 Agent cron job |
| 4.2 | Agent cron job 支持事件触发模式（非仅定时） |
| 4.3 | 去重逻辑：同一天同一标的只推一次买入信号 |
| 4.4 | 异常处理：K线数据失败 → 降级为仅价格检测 |

**验收**：盘中某标的满足条件 → 自动收到买入信号推送，无需手动盯盘

---

## 八、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 轮询频率 | 5分钟（不变） | A股T+1，不需要秒级。5分钟足够捕捉量价信号 |
| K线数据源 | 东方财富日K API | 免费、无认证、与现有行情数据源一致 |
| 两级决策 | 规则初筛 + Agent确认 | 规则做确定性计算，Agent做模糊推理，各取所长 |
| 信号去重 | 同一天同标的同信号只推1次 | 避免盘中多次骚扰 |
| 防抖 | 价格需连续2次轮询在介入区 | 避免瞬间刺入又拉回的假信号 |
| 状态重置 | 每日重置状态机 | 日线级别的信号，跨日无意义 |
| 降级策略 | K线失败 → 仅做价格检测 | 不因数据问题导致整个 poll 崩溃 |
| 不追板 | 涨幅≥7% → 强制 no_limit_up=False | 这是 UP 核心纪律，不可绕过 |

---

## 九、公开设计参考总结

| 参考来源 | 核心模式 | 本项目借鉴 |
|----------|---------|-----------|
| Zipline Pipeline API | 信号标准化 + 多因子检测 | BuySignal dataclass 标准化 |
| vnpy CTA 引擎 | 条件状态机 + 每标的独立状态 | BuySignalState 状态机 |
| Freqtrade | 事件驱动 + 回调注册 | K线变动 → 重新评估条件 |
| LLM-in-the-Loop (2024-2025) | 规则引擎 + LLM 确认的两级架构 | poll(规则) → Agent(确认) |
| Backtrader | 指标计算缓存 | K线数据缓存策略 |
| UP 方法论（本项目独有） | 缩量止跌→放量阳线的量价确认链 | 检测算法的核心逻辑来源 |

---

## 十、风险与不确定性

| 风险 | 影响 | 缓解 |
|------|------|------|
| 量价信号在震荡市中假阳性高 | 频繁推送「不买」 | 状态机防抖 + 连续确认要求 |
| Agent 单票分析超过 30s | poll 衔接延迟 | 异步触发（poll 不等待 Agent 返回） |
| K线 API 限流 | 数据获取失败 | 缓存在内存，单次失败用上次数据 |
| 停牌/涨跌停无法交易 | 信号无意义 | poll 检测 tradable 状态，停牌跳过 |
| 用户主观不认可 Agent 判断 | 信任度下降 | Agent 输出必须含理由，用户可反驳→反馈到 claims |

---

## 附录 A：与现有陷阱的关系

| 陷阱 | 关系 |
|------|------|
| 陷阱 14（条件驱动轮询未部署） | 本文档是该陷阱的解决方案 |
| 陷阱 15（设计文档 vs 代码差距） | 本文档是设计，实施后需对照检查 |
| 陷阱 20/21/23（cron 静默失败） | 新增信号检测后需验证 cron 管线正常 |
| 新增 陷阱 24 | 买入信号检测设计缺口（对应 `references/buy-signal-detection-gap.md`） |

## 附录 B：检测函数伪代码完整版

参见 `references/buy-signal-detection-algorithms.md`（待创建）。

---

> **下一步**：用户确认设计方向后，按 Phase 1-4 顺序实施。Phase 1（Agent 输出格式改造）可以立即开始，不改代码只改 prompt。
