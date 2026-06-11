# 买入信号自动检测系统 — 设计文档

> 版本: v1.2 | 日期: 2026-06-11 | 作者: Hermes + UP 方法论
>
> 目标：让系统像 UP 一样思考——观察池标的满足条件时，自动给出确定性的买入/不买信号，不再"永远在等"。
>
> **v1.2 修订说明**：增加**本地 K线缓存层**（SQLite）。开盘前（6:30）预拉取观察池+持仓池日K线，poll 层和 Agent 层均优先读本地，按需补充分时数据。解决 API 重复调用和延迟问题。
>
> **v1.1 修订说明**：基于项目全局架构 review，与 `config-cron-architecture-review.md` v2.0 已落地基础设施（Context Builder、daily_state、trader_mindset）深度融合，减少重复建设。

---

## 一、问题陈述

### 1.1 现状断层

```
当前：cron 定时 → Qing-Agent 全量分析 → 输出"等缩量企稳" → 用户自己盯盘
目标：poll 轮询 → poll 读本地K线筛选 → Agent 本地K线+实时分时确认 → 输出"买，现价X，止损Y"
```

### 1.2 根因

| 环节 | 现状 | 问题 |
|------|------|------|
| **触发机制** | 纯定时（9:26/9:45/10:00/...） | 条件满足了没触发，时间到了瞎分析 |
| **检测粒度** | 仅价格区间（add_zone） | 不做量价配合判断，缺了 UP 最核心的"缩量→放量转折"识别 |
| **Agent 模式** | 全量 market 分析 | 一次分析所有标的→每只票只能得到一句话，无法深度研判 |
| **输出格式** | "可买：等缩量企稳" | 永远在"等"，用户误以为是买入信号（如 6/11 中化国际涨停） |
| **数据延迟** | Agent 每次分析现拉 K线 | 网络 I/O 慢，分析延迟高，API 调用频繁 |

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
- **可借鉴**：状态机管理每个标的的买入条件生命周期，以及**无效化条件**（条件消失时回退）

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

**模式 E：本地缓存层（Data Cache）**
```
开盘前批量拉取日K → 写入本地 SQLite → 盘中各组件优先读本地 → 按需补充分时
```
- 代表设计：Backtrader DataFeed、vnpy DataManager
- 核心思想：日K数据日维度不变，开盘前预加载一次，全天共享
- **可借鉴**：减少 API 重复调用，将网络 I/O 转为本地 I/O，提速 10-100 倍

### 2.2 本项目选型

结合以上模式和现有基础设施（5分钟轮询 cron + Qing-Agent + 微信推送 + daily_state.json），选择**模式 C + B + E 混合**：

```
06:30 预拉取 cron → 批量拉取日K → 写入 SQLite
                              ↓
09:30-15:00 poll(5min) → 读本地 SQLite K线 → 候选筛选 → 写入 daily_state
                              ↓
cron 定时触发 → Agent 读本地 SQLite K线 + 按需拉分时 → 深度确认 → 微信推送
```

选择理由：
1. **不引入事件总线**：当前是 cron 轮询架构，引入实时事件总线改动太大。5分钟轮询在 A 股 T+1 环境下足够
2. **本地 K线缓存**：开盘前预拉取一次日K（约 50-100 只标的），写入 SQLite，全天共享。poll 和 Agent 均优先读本地，将网络 I/O 转为本地 I/O
3. **分时按需实时拉取**：盘中分时数据变化快，只在 Agent 分析时按需拉取，结合本地日K做完整判断
4. **复用 daily_state**：不新增独立状态机，使用 `daily_state.json` 的 `active_opportunities` 承载买入信号状态
5. **复用 analysis_type="stock"**：Qing-Agent 已支持个股分析模式，不新增 `single_stock` analysis_type

---

## 三、系统架构

### 3.1 整体数据流

```
┌─────────────────────────────────────────────────────────────────────────┐
│  cron: pre_fetch_klines.py（06:30，no_agent）                          │
│                                                                         │
│  1. 读取 watchlist.yaml + positions.yaml → 全部股票代码列表             │
│  2. 批量拉取日K线（东方财富 API，90根，分批次防限流）                   │
│  3. 写入 SQLite: stocks_kline（覆盖写入，新交易日刷新）                 │
│  4. 写入标记: ~/.qing_kline_cache/ready_YYYYMMDD                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  cron: qing_stock_monitor_poll.py (每5分钟，no_agent)                   │
│                                                                         │
│  5. 拉取实时行情（东方财富 API）✅ 已有                                 │
│  6. 【改造】evaluate_buy_signal_candidates()                            │
│     ├── 读本地 SQLite K线（近5-10日）                                   │
│     ├── 价格区间检测（已有：add_zone / entry_zone）                     │
│     ├── 轻量价筛选（本地 K线即可计算）                                  │
│     │      ├── 缩量止跌：近3日成交量递减 + 振幅收敛                     │
│     │      ├── 均线位置：收盘价 vs MA5/MA10/MA20                        │
│     │      └── 未涨停：当日涨幅 < 7%（实时行情）                        │
│     └── 候选标记写入 daily_state.json → active_opportunities            │
│  7. 【可选】推送精简提醒：【机会候选】XX 价格进入介入区                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ 下一个 cron 节点触发
┌─────────────────────────────────────────────────────────────────────────┐
│  cron: qing_stock_monitor_agent.py（定时触发）                          │
│                                                                         │
│  8. 检测 daily_state 中是否有 status="候选" 的机会                      │
│  9. 若有 → POST /analyze/trigger                                        │
│     ├── analysis_type: "stock"（复用已有）                              │
│     ├── trigger.kind: "buy_signal_candidate"                            │
│     ├── stock_code / stock_name / entry_zone / stop_loss                │
│     └── 注入 claim_basis / odds_analysis 上下文                         │
│  10. Agent 收到触发 → stock_analyst 节点深度分析                        │
│     ├── 【优先】读本地 SQLite K线（20-90日，已预拉取）                  │
│     ├── 【按需】拉取当日分时数据（实时 API）                            │
│     ├── 量价关系验证（缩量止跌？放量阳线？均线支撑？）                    │
│     ├── 板块联动状态（已有 sector_data）                                │
│     ├── 大盘环境（全A指数涨跌+量能）                                    │
│     ├── UP 相关 claims（已有 Context Builder）                          │
│     └── 【强制】赔率计算（>= 2:1 ?）                                    │
│  11. Agent 输出二值化结论                                               │
│     ├── 🟢 买入：现价/介入区间/止损/理由/风险/赔率                      │
│     └── 🔴 不买：原因（具体到不满足哪个条件）/ 建议                     │
│  12. 推送到微信                                                         │
│  13. 结果写回 daily_state.json → status="确认买入"/"不买"               │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 组件职责

| 组件 | 位置 | 职责 | 状态 |
|------|------|------|------|
| **K线预拉取** | `scripts/pre_fetch_klines.py` | 开盘前批量拉取 watchlist + positions 全部日K，写入 SQLite | 🆕 新增 |
| **K线缓存** | `infra/data/kline_cache.db` (SQLite) | 存储个股日K，开盘前刷新，盘中只读 | 🆕 新增 |
| 行情拉取 | `stock_monitor.py::fetch_quotes_eastmoney()` | 拉取 watchlist 全部实时行情 | ✅ 已有 |
| 价格区间检测 | `stock_monitor.py::evaluate_position_alerts()` | add_zone / entry_zone 进入检测 | ✅ 已有 |
| **候选筛选** | `stock_monitor.py::evaluate_buy_signal_candidates()` | 读本地 SQLite K线，做价格+量价筛选 | 🆕 设计 |
| **状态承载** | `daily_state.json` 的 `active_opportunities` | 替代独立 `BuySignalState` | ✅ 已有，🔧 扩展 |
| 去重/推送 | `stock_monitor.py::filter_new_alerts()` | 价格分桶+时间窗口去重 | ✅ 已有，🔧 扩展 |
| Agent 触发 | `stock_monitor.py::find_agent_analysis_trigger()` | 检测到 daily_state 候选时触发 stock 分析 | 🔧 改造 |
| **Agent K线读取** | `stock_data.py::fetch_stock_kline()` | **优先查 SQLite → 无则拉 API → 写入 SQLite** | 🔧 改造 |
| **Agent 分时读取** | `stock_data.py::fetch_stock_intraday()` | 按需实时拉取（每次分析时） | ✅ 已有 |
| Agent 分析 | Qing-Agent `stock_analyst` 节点 | 单票深度研判（本地K线+分时+板块+claims+赔率）→ 二值化 | ✅ 已有，🔧 扩展 prompt |

---

## 四、信号定义

### 4.1 买入信号类型

```python
@dataclass
class BuySignalCandidate:
    """买入信号候选（poll 层输出，不是最终信号）"""
    stock_code: str
    stock_name: str
    price: float
    candidate_type: str  # "candidate" | "not_candidate"
    
    # 筛选条件（基于本地 SQLite K线 + 实时行情）
    price_in_zone: bool        # 价格进入介入区间
    not_crashing: bool         # 当日非大跌（pct_change > -3%）
    no_limit_up: bool          # 未涨停（pct_change < 7%）
    has_claim_support: bool    # 有 claim_basis（UP 明确看好）
    
    # 【新增】基于本地 K线的轻量量价条件
    volume_shrinking: bool     # 近3日缩量（本地 K线计算）
    above_key_ma: bool         # 收盘在 MA20 上方（本地 K线计算）
    
    # 综合
    is_candidate: bool         # 满足 >=4/6 条件 → 候选
    matched_conditions: list[str]
    
    # 上下文
    entry_zone: tuple[float, float]
    stop_loss: float
    claim_basis: str
    odds_analysis: dict
```

**设计原则**：poll 层基于**本地 SQLite K线**做轻量量价筛选（缩量和均线位置），把"明显不符合"的票提前过滤掉。深度量价分析（放量阳线确认、板块联动、赔率计算）仍下沉到 Qing-Agent。

### 4.2 检测算法（poll 层——读本地 SQLite）

```python
def evaluate_buy_signal_candidates(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[BuySignalCandidate]:
    """
    基于本地 SQLite K线 + 实时行情做候选筛选。
    判断"这只票是否值得 LLM 做深度买入确认"。
    """
    from qing_investment.kline_cache import get_kline, get_ma
    
    candidates = []
    
    for stock in watchlist_stocks + position_stocks:
        quote = get_quote(stock.code)
        if not quote:
            continue
            
        entry = get_entry_point(stock.code) or get_add_zone(stock.code)
        if not entry:
            continue
        
        price = quote.latest
        pct_change = quote.pct_change
        
        # --- 实时行情条件 ---
        price_in_zone = entry.zone_low <= price <= entry.zone_high
        not_crashing = pct_change > -3.0
        no_limit_up = pct_change < 7.0
        has_claim_support = bool(entry.get("claim_basis"))
        
        # --- 本地 K线条件（SQLite 读取，零网络延迟）---
        kline = get_kline(stock.code, days=5)  # 读本地 SQLite
        volume_shrinking = False
        above_key_ma = False
        
        if len(kline) >= 4:
            # 缩量：近3日成交量递减
            vols = [d['volume'] for d in kline[-3:]]
            volume_shrinking = vols[0] < vols[1] < vols[2]
            
            # MA20 支撑：收盘在 MA20 上方
            ma20 = get_ma(stock.code, days=20)
            above_key_ma = kline[-1]['close'] > ma20 if ma20 else False
        
        # 六项条件，满足 4/6 即入选候选
        conditions = {
            "价格进入区间": price_in_zone,
            "非系统性大跌": not_crashing,
            "未涨停": no_limit_up,
            "UP明确看好": has_claim_support,
            "近3日缩量": volume_shrinking,
            "MA20上方": above_key_ma,
        }
        matched = [k for k, v in conditions.items() if v]
        is_candidate = len(matched) >= 4
        
        candidates.append(BuySignalCandidate(
            stock_code=stock.code,
            stock_name=stock.name,
            price=price,
            candidate_type="candidate" if is_candidate else "not_candidate",
            price_in_zone=price_in_zone,
            not_crashing=not_crashing,
            no_limit_up=no_limit_up,
            has_claim_support=has_claim_support,
            volume_shrinking=volume_shrinking,
            above_key_ma=above_key_ma,
            is_candidate=is_candidate,
            matched_conditions=matched,
            entry_zone=(entry.zone_low, entry.zone_high),
            stop_loss=entry.stop_loss,
            claim_basis=entry.get("claim_basis", ""),
            odds_analysis=entry.get("odds_analysis", {}),
        ))
    
    return candidates
```

### 4.3 深度检测算法（Agent 层——本地K线+按需分时）

Qing-Agent 的 `stock_analyst` 节点在分析时：

**Step 1: 优先读本地 SQLite K线**
```python
# stock_data.py 改造后
def fetch_stock_kline(stock_code: str, days: int = 30) -> list[dict]:
    """优先查本地 SQLite，无则拉 API，拉完后写入 SQLite"""
    # 1. 查本地
    local = kline_cache.get(stock_code, days=days)
    if local and len(local) >= days * 0.8:
        return local
    
    # 2. 本地不足 → 拉 API
    remote = _fetch_from_eastmoney(stock_code, days=days)
    
    # 3. 写入本地缓存
    kline_cache.save(stock_code, remote)
    return remote
```

**Step 2: 按需拉取当日分时**
```python
def fetch_stock_intraday(stock_code: str) -> list[dict]:
    """分时数据盘中实时变化，每次分析时按需拉取，不缓存"""
    return _fetch_intraday_from_eastmoney(stock_code)
```

**Step 3: Agent prompt 检查清单**
```
【买入确认检查清单——你必须逐项验证】

1. 缩量止跌验证
   - 读本地 SQLite K线（已预拉取 90 日）
   - 近3日成交量是否递减？
   - 近3日最低价是否不再创新低？
   - 近3日振幅是否收敛（K线实体变小）？

2. 放量阳线验证
   - 读本地 SQLite K线：当日量是否 > 5日均量 × 1.2？
   - 当日是否阳线（close > open）？
   - 【结合实时行情】当前价格 vs 开盘价，确认阳线状态

3. 均线支撑验证
   - 读本地 SQLite K线：MA5/MA10/MA20 数值
   - 收盘价是否在 MA20 上方？
   - MA5 是否上穿 MA10（金叉）？

4. 分时结构验证（按需拉取实时分时）
   - 分时是否呈现"早盘放量拉升 → 盘中缩量整理 → 尾盘企稳"的健康结构？
   - 或"全天温和放量，无尖顶出货"？

5. 板块联动验证（已有 sector_data）
6. 大盘环境验证（daily_state 中的 market_stage）
7. UP Claims 验证（Context Builder 已注入）
8. 【强制】赔率计算：>= 2:1 ?
```

### 4.4 条件状态机（基于 daily_state.json）

同 v1.1，使用 `daily_state.json` 的 `active_opportunities` 承载状态：

```
                    ┌──────────┐
        价格未进入    │  未触发   │  全部条件不满足
       ──────────────│  (idle)  │────────────────
                     └────┬─────┘
                          │ 价格进入介入区间 + 满足 4/6 候选条件
                          ▼
                    ┌──────────┐
     价格持续在区间内 │   候选    │  写入 daily_state
    （连续2次轮询）  │(candidate)│  active_opportunities.status="候选"
       ─────────────│          │────────────────
                     └────┬─────┘
                          │ cron 触发 stock_analyst 分析
                          ▼
                    ┌──────────┐
     Agent 分析中    │ Agent分析 │  status="分析中"
       ─────────────│(analyzing)│────────────────
                     └────┬─────┘
                          │ Agent 输出二值化结论
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        ┌────────┐  ┌────────┐  ┌────────┐
        │ 确认买入 │  │  不买   │  │  失效   │
        │(buy)   │  │(reject)│  │(expired)│
        └────────┘  └────────┘  └────────┘
                          ▲
                          │ 价格跌破介入区间下沿
                          │ 或板块集体走弱
                          │ 或大盘破位
```

**防抖与去重**：
- `未触发 → 候选`：价格需连续 2 次轮询（10分钟）在介入区间内
- 全天去重：价格分桶 + 4 小时窗口（同 v1.1）

---

## 五、Agent 单票分析模式

### 5.1 API 设计（复用 `analysis_type="stock"`）

同 v1.1，复用已有 `analysis_type="stock"`，通过 `trigger.kind` 区分：

```python
POST /analyze/trigger
{
  "analysis_type": "stock",
  "stock_code": "600378",
  "stock_name": "昊华科技",
  "trigger": {
    "kind": "buy_signal_candidate",
    "title": "买入信号候选",
    "reason": "价格进入介入区间 51.5-53.0，满足 5/6 候选条件",
    "context": {
      "entry_zone": [51.5, 53.0],
      "stop_loss": 49.8,
      "current_price": 52.30,
      "claim_basis": "claim-20260604-003",
      "odds_analysis": {"upside_pct": 15, "downside_pct": 5, "odds_ratio": "3:1"},
      "kline_source": "sqlite"  # 提示 Agent 优先读本地
    }
  }
}
```

### 5.2 Agent Prompt 约束（买入确认模式）

在 `stock_analyst.txt` 中新增：

```
你是青枫浦上Q风格的A股交易分析助手。当前进行【单票买入确认】分析。

【数据来源优先级】
1. 本地 SQLite K线（已预拉取 90 日，开盘前刷新）→ 用于缩量/放量/均线判断
2. 实时行情快照 → 用于当前价格/涨跌幅/未涨停确认
3. 按需拉取分时数据 → 用于日内结构验证
4. 板块数据 + claims → 已有 Context Builder 注入

【强制检查清单】
（同 4.3，略）

【输出格式】🟢买入 / 🔴不买 二值化
（同 v1.1，略）
```

### 5.3 二值化输出 → 微信推送

同 v1.1。

---

## 六、与现有系统的集成

### 6.1 改动清单

| 文件 | 改动 | 类型 |
|------|------|------|
| `scripts/pre_fetch_klines.py` | **新增**：开盘前批量拉取日K，写入 SQLite | 🆕 新增 |
| `src/qing_investment/kline_cache.py` | **新增**：SQLite 封装（读/写/查MA/查成交量） | 🆕 新增 |
| `src/qing_investment/agent/tools/stock_data.py` | **改造**：`fetch_stock_kline()` 优先查 SQLite → 无则拉 API → 写入 SQLite | 🔧 改造 |
| `src/qing_investment/stock_monitor.py` | 新增 `evaluate_buy_signal_candidates()`，读本地 SQLite K线 | 🆕 设计 |
| `src/qing_investment/stock_monitor.py` | `evaluate_monitor_alerts()` 追加 buy_signal alerts | 修改 |
| `src/qing_investment/stock_monitor.py` | `find_agent_analysis_trigger()` 检测 daily_state 候选 | 改造 |
| `src/qing_investment/agent/prompts/system/stock_analyst.txt` | 新增"买入确认模式" prompt 分支 + 数据源优先级说明 | 修改 |
| `src/qing_investment/agent/graph/nodes.py` | `stock_analyst` 识别 `trigger.kind="buy_signal_candidate"` | 改造 |
| `scripts/hermes_stock_monitor_agent.py` | 若 daily_state 有候选，POST 时设置 `analysis_type="stock"` + `trigger.kind` | 改造 |
| `tools/daily_state.py` | 扩展 `active_opportunities` 状态枚举 | 扩展 |
| `skills/qing-stock-monitor-update/SKILL.md` | 新增陷阱 24、25、26 | 文档 |

### 6.2 新增 cron job：开盘前 K线预拉取

```
Cron: pre_fetch_klines.py
时间：30 6 * * 1-5（周一到周五 06:30）
类型：no-agent
超时：300 秒（批量拉取 50-100 只标的，分批次，防限流）

执行逻辑：
1. 读取 watchlist.yaml → 提取全部 stock.code
2. 读取 positions.yaml → 提取全部持仓 code（去重）
3. 合并去重 → 总代码列表（约 50-100 只）
4. 分批次拉取日K（每批 10 只，间隔 1 秒，防东财限流）
5. 写入 SQLite: infra/data/kline_cache.db → stocks_kline 表（覆盖写入）
6. 写入标记文件: infra/data/.kline_ready_YYYYMMDD
```

### 6.3 K线数据获取策略

**日K数据（变化慢，预加载）**：
- 数据源：东方财富日K API
- 刷新频率：**每日开盘前一次**（06:30 cron）
- 存储：SQLite `stocks_kline` 表
- 读取方：poll 层候选筛选、Agent 层深度分析
- 访问方式：**优先本地 SQLite，无则拉 API**

**分时数据（变化快，实时拉）**：
- 数据源：东方财富/腾讯分时 API
- 刷新频率：**按需实时拉取**（Agent 分析时）
- 存储：**不缓存**（盘中每分钟都在变）
- 读取方：仅 Agent 层（日内结构验证）

**实时行情（变化最快，轮询拉）**：
- 数据源：东方财富实时行情 API
- 刷新频率：**每 5 分钟 poll 拉取**
- 存储：内存（不持久化）
- 读取方：poll 层价格检测

### 6.4 云端部署注意事项

> 本项目开发在本地 macOS，代码推送到远端后由云端 Hermes 维护。云端环境特点：**无 Docker**、Qdrant/Neo4j 均为**本地进程**、SQLite 为**纯文件数据库**。

#### 6.4.1 SQLite 是云端部署的优势

| 数据库 | 需要服务进程 | 需要 Docker | 云端适用性 |
|--------|-------------|------------|-----------|
| SQLite | ❌ 不需要 | ❌ 不需要 | ⭐⭐⭐ 完美匹配 |
| PostgreSQL | ✅ 需要 | ⚠️ 推荐 | 无 Docker 时手动维护成本高 |
| MySQL | ✅ 需要 | ⚠️ 推荐 | 同上 |
| DuckDB | ❌ 不需要 | ❌ 不需要 | ⭐⭐ 也可以，但多一个 pip install |

SQLite 是纯文件数据库，**不受"无 Docker"限制**，这是选择它的核心原因之一。

#### 6.4.2 时区对齐（关键）

云端服务器默认时区可能是 **UTC**，而 A 股交易时间是 `Asia/Shanghai`（CST, UTC+8）。

**风险**：如果云端服务器时区为 UTC，`pre_fetch_klines.py` 的 06:30 cron 实际在 **北京时间 14:30** 执行（收盘后），全天无本地 K线可用。

**解决方案**：
```python
# pre_fetch_klines.py 开头强制校验时区
import os
from datetime import datetime
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")
now_cn = datetime.now(CN_TZ)

# 校验：必须在 A 股开盘前执行（06:00-09:15）
if not (6 <= now_cn.hour < 9 or (now_cn.hour == 9 and now_cn.minute < 15)):
    print(f"[SKIP] 当前时间 {now_cn.strftime('%H:%M')} 不是预拉取窗口（06:00-09:15 CST）")
    return 0
```

同时，Hermes cron 配置中的 `06:30` 也应基于服务器本地时间确认，或在 cron 表达式中显式指定时区：
```
# 如果 Hermes cron 支持时区配置
schedule: "30 6 * * 1-5"
timezone: "Asia/Shanghai"  # 显式声明
```

#### 6.4.3 SQLite 文件生命周期

- **`.gitignore` 已配置**：`infra/data/` 目录已在 `.gitignore` 中，SQLite 文件不会随代码推送
- **云端首次运行**：`init_db()` 会自动创建 `infra/data/kline_cache.db`，无需手动同步
- **无需备份**：K线数据是每日重新拉取的公开数据，丢失后次交易日自动重建
- **磁盘占用**：< 10MB，任何云服务器磁盘都足够

#### 6.4.4 东财 API 限流（云端固定 IP）

云端服务器的**出口 IP 是固定的**（或从有限 IP 池出），批量拉取 100 只票容易触发东财 API 的限流/封禁。

**缓解措施**（已在 pre_fetch 中实现）：
- 分批次拉取：每批 **5-10 只**，间隔 **2-3 秒**
- 单只失败重试：失败时等待 5 秒后重试，最多 3 次
- 整体超时保护：单只超时 30 秒，整体 cron 超时 600 秒
- User-Agent 轮换：模拟浏览器请求头，降低被封概率

#### 6.4.5 SQLite 并发安全（WAL 模式）

云端场景：
- `pre_fetch_klines.py`（06:30）→ **写入** SQLite
- `qing_stock_monitor_poll.py`（09:30-15:00）→ **读取** SQLite
- `qing-agent stock_analyst`（09:30-15:00）→ **读取** SQLite

**时间错开原则**：pre_fetch 在 06:30 执行，此时 poll 和 Agent 尚未启动（09:30 才开始），正常情况下不存在并发写入。

**但为防异常**（pre_fetch 执行超时、云端时间不同步），SQLite 启用 **WAL 模式**：
```python
# kline_cache.py
conn.execute("PRAGMA journal_mode=WAL;")        # 写前日志，支持多读单写
conn.execute("PRAGMA synchronous=NORMAL;")      # 性能与安全的平衡
conn.execute("PRAGMA temp_store=MEMORY;")       # 临时表放内存，加速
```

WAL 模式会产生两个临时文件：
- `kline_cache.db-wal`（写前日志）
- `kline_cache.db-shm`（共享内存映射）

这两个文件在 `infra/data/` 目录下，也受 `.gitignore` 保护。若进程 crash 导致残留，SQLite 下次打开时会**自动恢复**。

#### 6.4.6 Hermes Cron 集成

`pre_fetch_klines.py` 需要加入云端 Hermes 的 cron 调度：

```
# ~/.hermes/cron/jobs/ 下的配置（或 Hermes 管理后台）
{
  "id": "pre_fetch_klines",
  "name": "开盘前K线预拉取",
  "schedule": "30 6 * * 1-5",
  "script": "qing_pre_fetch_klines.py",
  "timeout": 600,
  "timezone": "Asia/Shanghai"
}
```

wrapper 脚本（`scripts/hermes_pre_fetch_klines.py`）：
```python
#!/usr/bin/env python3
"""Hermes cron wrapper for pre_fetch_klines.py"""
import subprocess
import sys
import os
from pathlib import Path

def repo_root() -> str:
    configured = os.environ.get("HERMES_REPO_ROOT")
    if configured:
        return configured
    return str(Path(__file__).resolve().parents[1])

def main():
    root = Path(repo_root())
    venv_python = root / ".venv" / "bin" / "python"
    python_cmd = str(venv_python) if venv_python.exists() else "python3"
    
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["TZ"] = "Asia/Shanghai"  # 强制时区
    
    return subprocess.call(
        [python_cmd, "-m", "qing_investment.pre_fetch_klines"],
        cwd=root,
        env=env,
    )

if __name__ == "__main__":
    raise SystemExit(main())
```

**注意**：wrapper 脚本需要复制/软链到 `~/.hermes/scripts/qing_pre_fetch_klines.py`（遵循 AGENTS.md 的命名规范）。

#### 6.4.7 降级策略（云端网络异常）

若预拉取失败（东财限流、网络中断），poll 和 Agent 的 fallback 链：

```
pre_fetch 失败
    ↓
poll 检测：发现 SQLite 无数据 → 跳过 K线条件，仅做价格筛选
    ↓
Agent 分析：fetch_stock_kline() 发现 SQLite miss → 自动调用 API 补拉
    ↓
若 API 也失败 → Agent 明确告知"K线数据不足，无法确认量价关系"
```

整个系统**不会因为预拉取失败而崩溃**，只是退化为 v1.1 的行为（ poll 不做 K线筛选，Agent 按需拉取）。

---

## 七、实施计划

### Phase 0: K线缓存基础设施（2-3小时）

**目标**：建立本地 SQLite K线缓存，开盘前预拉取

| 任务 | 内容 |
|------|------|
| 0.1 | 创建 `src/qing_investment/kline_cache.py`：SQLite 封装（初始化表、save、get、get_ma、get_volume） |
| 0.2 | 创建 `scripts/pre_fetch_klines.py`：开盘前批量拉取日K cron 脚本 |
| 0.3 | 改造 `src/qing_investment/agent/tools/stock_data.py`：`fetch_stock_kline()` 优先查 SQLite |
| 0.4 | 测试：手动运行 pre_fetch_klines.py → 确认 SQLite 写入 → poll/Agent 读取验证 |

**验收**：`sqlite3 infra/data/kline_cache.db "SELECT code, trade_date, close FROM stocks_kline LIMIT 5;"` 有数据

### Phase 1: Agent 输出格式改造（1-2小时）

同 v1.1 Phase 1，增加"数据源优先级"说明。

### Phase 2: poll 候选筛选（读本地 K线）（2-3小时）

**目标**：poll 基于本地 SQLite K线做轻量量价筛选

| 任务 | 内容 |
|------|------|
| 2.1 | 实现 `BuySignalCandidate` dataclass（含 volume_shrinking、above_key_ma） |
| 2.2 | 实现 `evaluate_buy_signal_candidates()`，读本地 SQLite K线 |
| 2.3 | 集成到 `evaluate_monitor_alerts()` |
| 2.4 | 候选写入 daily_state.json |
| 2.5 | 单元测试：验证 K线读取 → 缩量/MA 计算 → 候选判断 |

**验收**：poll 运行时日志中看到 "volume_shrinking=true, above_key_ma=true" 等标记

### Phase 2.5: 历史回测验证（强烈推荐，2-3小时）

同 v1.1 Phase 2.5。回测脚本优先读本地 SQLite 缓存，加速回测。

### Phase 3: Agent 单票分析链路（2-3小时）

同 v1.1 Phase 3。Agent 分析时体验应明显加快（K线从本地读取，<10ms）。

### Phase 4: 全自动闭环（2-3小时）

同 v1.1 Phase 4。

---

## 八、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| **日K刷新策略** | **开盘前预拉取一次（06:30）** | 日K数据日维度不变，预加载后全天共享，API 调用从"每次分析都拉"降到"每天一次" |
| **日K存储** | **SQLite 本地文件** | 轻量、零配置、Python 内置支持、查询速度 <10ms |
| **分时策略** | **按需实时拉取，不缓存** | 分时数据盘中每分钟变，缓存无意义 |
| **K线读取优先级** | **本地 SQLite → API → 写入本地** | 本地 miss 时自动补全，次日即可从本地读取 |
| poll 检测深度 | 读本地 K线做轻量量价筛选（缩量+MA） | 比纯价格筛选更精准，但比 Agent 深度分析轻量 |
| Agent 检测深度 | 本地 K线 + 按需分时 + 板块 + claims + 赔率 | 完整深度分析，本地 K线保证速度 |
| 轮询频率 | 5分钟（不变） | A股T+1，5分钟足够 |
| 状态机载体 | `daily_state.json` 的 `active_opportunities` | 与观点连续性融合 |
| analysis_type | 复用 `"stock"` | 已有支持 |
| 赔率底线 | Agent 强制计算，< 2:1 不买 | 与 trader_mindset 对齐 |

---

## 九、风险与不确定性

| 风险 | 影响 | 缓解 |
|------|------|------|
| 预拉取 cron 失败（东财 API 限流/网络问题） | 全天无本地 K线，poll 和 Agent 都降级为纯价格分析 | cron 失败时发送告警；poll/Agent 检测到无本地 K线时自动 fallback 到 API 拉取 |
| SQLite 并发读写（poll 读 + Agent 读 + pre_fetch 写） | 锁冲突或数据不一致 | SQLite WAL 模式（Write-Ahead Logging）支持多读单写；pre_fetch 在 06:30 执行，与 poll/Agent 时间错开 |
| 预拉取标的数过多导致超时 | 06:30 cron 在 09:30 前未完成 | 分批次拉取（每批10只，间隔1秒）；设置超时 300 秒；监控执行时间 |
| 新股/次新股历史 K线不足 | MA20 计算失败 | `get_ma()` 返回 None，poll 跳过该条件（不影响其他 5 项） |
| 停牌票预拉取无数据 | SQLite 中无记录 | pre_fetch 跳过停牌票；poll 检测到无 K线时跳过量价条件 |

---

## 十、附录

### 附录 A：SQLite Schema

```sql
-- stocks_kline: 日K线数据，每日开盘前预拉取，覆盖写入
CREATE TABLE IF NOT EXISTS stocks_kline (
    code TEXT NOT NULL,           -- 股票代码，如 "600378"
    trade_date TEXT NOT NULL,     -- 交易日期，如 "2026-06-11"
    open REAL,                    -- 开盘价
    high REAL,                    -- 最高价
    low REAL,                     -- 最低价
    close REAL,                   -- 收盘价
    volume REAL,                  -- 成交量（手）
    turnover REAL,                -- 成交额（元）
    amplitude REAL,               -- 振幅（%）
    pct_change REAL,              -- 涨跌幅（%）
    updated_at TEXT,              -- 数据写入时间
    PRIMARY KEY (code, trade_date)
);

-- 按 code + date 查询的索引
CREATE INDEX IF NOT EXISTS idx_kline_code_date 
    ON stocks_kline(code, trade_date);

-- meta: 记录最后预拉取时间
CREATE TABLE IF NOT EXISTS kline_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

### 附录 B：K线缓存 Python API

```python
# src/qing_investment/kline_cache.py
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parents[3] / "infra" / "data" / "kline_cache.db"

@contextmanager
def _get_conn(write: bool = False):
    """获取 SQLite 连接，自动配置 WAL 模式和超时。
    
    write=True: 预拉取脚本使用（独占写入）
    write=False: poll/Agent 使用（只读或并发安全读取）
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    
    # WAL 模式：支持多读单写，适合云端"pre_fetch 写 + poll/Agent 读"场景
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    
    if not write:
        # poll/Agent 只读时启用 query_only，防止意外写入
        conn.execute("PRAGMA query_only=ON;")
    
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """初始化 SQLite 表结构（首次运行时自动创建）"""
    with _get_conn(write=True) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS stocks_kline (
                code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                turnover REAL,
                amplitude REAL,
                pct_change REAL,
                updated_at TEXT,
                PRIMARY KEY (code, trade_date)
            );
            CREATE INDEX IF NOT EXISTS idx_kline_code_date 
                ON stocks_kline(code, trade_date);
            CREATE TABLE IF NOT EXISTS kline_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        conn.commit()

def save_klines(code: str, klines: list[dict]):
    """保存单只股票的日K线（覆盖写入该股票的历史数据）"""
    with _get_conn(write=True) as conn:
        # 先删除该股票旧数据，再插入新数据（覆盖策略）
        conn.execute("DELETE FROM stocks_kline WHERE code = ?", (code,))
        conn.executemany(
            """INSERT INTO stocks_kline 
                (code, trade_date, open, high, low, close, volume, turnover, amplitude, pct_change, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    code,
                    d["date"], d["open"], d["high"], d["low"], d["close"],
                    d.get("volume"), d.get("turnover"), d.get("amplitude"),
                    d.get("pct_change"), d.get("updated_at", ""),
                )
                for d in klines
            ],
        )
        conn.commit()

def get_klines(code: str, days: int = 30) -> list[dict]:
    """读取最近 N 日 K线，按 trade_date 升序"""
    with _get_conn(write=False) as conn:
        cursor = conn.execute(
            """SELECT * FROM stocks_kline 
                WHERE code = ? 
                ORDER BY trade_date DESC 
                LIMIT ?""",
            (code, days),
        )
        rows = cursor.fetchall()
        # 返回正序（旧→新）
        return [dict(row) for row in reversed(rows)]

def get_ma(code: str, days: int = 20) -> float | None:
    """计算最近 N 日收盘价的移动平均，K线不足返回 None"""
    klines = get_klines(code, days=days)
    if len(klines) < days:
        return None
    return sum(d["close"] for d in klines) / days

def is_cache_ready(date: str | None = None) -> bool:
    """检查某交易日 K线是否已预拉取"""
    if date is None:
        from datetime import datetime, timezone, timedelta
        date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    
    with _get_conn(write=False) as conn:
        cursor = conn.execute(
            "SELECT value FROM kline_meta WHERE key = ?",
            (f"ready_{date}",),
        )
        row = cursor.fetchone()
        return row is not None

def mark_cache_ready(date: str):
    """标记某交易日预拉取已完成"""
    with _get_conn(write=True) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO kline_meta (key, value) VALUES (?, ?)",
            (f"ready_{date}", date),
        )
        conn.commit()
```

### 附录 C：预拉取脚本伪代码

```python
# scripts/pre_fetch_klines.py
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from qing_investment.kline_cache import init_db, save_klines, mark_cache_ready
from qing_investment.stock_monitor import load_watchlist, load_positions
from qing_investment.agent.tools.stock_data import fetch_stock_kline

CN_TZ = timezone(timedelta(hours=8))

def main():
    # === 云端时区校验（关键）===
    now_cn = datetime.now(CN_TZ)
    
    # 必须在 A 股开盘前执行（06:00-09:15 CST）
    if not (6 <= now_cn.hour < 9 or (now_cn.hour == 9 and now_cn.minute < 15)):
        print(f"[SKIP] 当前时间 {now_cn.strftime('%H:%M')} 不是预拉取窗口（06:00-09:15 CST）")
        return 0
    
    # 检查环境变量强制时区（云端服务器可能是 UTC）
    if os.environ.get("TZ") != "Asia/Shanghai":
        print("[WARN] 建议设置 TZ=Asia/Shanghai 确保时区正确")
    
    init_db()
    
    # 1. 获取全部代码（watchlist + positions 去重）
    codes = set()
    for stock in load_watchlist() + load_positions():
        codes.add(stock.code)
    codes = sorted(codes)
    print(f"[{now_cn.strftime('%H:%M')}] 预拉取 {len(codes)} 只标的日K线...")
    
    # 2. 分批次拉取（云端固定 IP，限流风险更高，批次更小、间隔更长）
    BATCH_SIZE = 5          # 每批 5 只（保守）
    DELAY_BETWEEN_BATCH = 3.0  # 批次间隔 3 秒
    DELAY_BETWEEN_STOCK = 0.5  # 单只间隔 0.5 秒
    MAX_RETRIES = 3
    TIMEOUT_PER_STOCK = 30   # 单只超时 30 秒
    
    success_count = 0
    fail_count = 0
    
    for i in range(0, len(codes), BATCH_SIZE):
        batch = codes[i:i+BATCH_SIZE]
        for code in batch:
            klines = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    klines = fetch_stock_kline(code, days=90)
                    break
                except Exception as e:
                    print(f"  ⚠️ {code}: 第{attempt}次失败 ({e})")
                    if attempt < MAX_RETRIES:
                        time.sleep(5 * attempt)  # 指数退避：5s, 10s
                    else:
                        print(f"  ❌ {code}: 重试耗尽，跳过")
            
            if klines:
                save_klines(code, klines)
                success_count += 1
                print(f"  ✅ {code}: {len(klines)} 根K线")
            else:
                fail_count += 1
                # 停牌或无数据的票，记录空标记避免反复拉取
                save_klines(code, [])
            
            time.sleep(DELAY_BETWEEN_STOCK)
        
        # 批次间延迟（防东财限流）
        if i + BATCH_SIZE < len(codes):
            time.sleep(DELAY_BETWEEN_BATCH)
    
    # 3. 标记完成
    today = now_cn.strftime("%Y-%m-%d")
    mark_cache_ready(today)
    
    print(f"预拉取完成: ✅{success_count} ❌{fail_count} 总计{len(codes)}")
    return 0 if fail_count <= len(codes) * 0.2 else 1  # 失败率>20%返回非0，cron可告警

if __name__ == "__main__":
    raise SystemExit(main())
```

### 附录 D：与现有陷阱的关系

| 陷阱 | 关系 |
|------|------|
| 陷阱 14（条件驱动轮询未部署） | 本文档是候选筛选的解决方案 |
| 陷阱 15（设计文档 vs 代码差距） | v1.2 已与 SQLite 缓存、pre_fetch cron 设计对齐 |
| 陷阱 20/21/23（cron 静默失败） | pre_fetch 失败需告警，poll/Agent 需 fallback |
| 陷阱 24 | Agent 输出标签语义矛盾 → 二值化输出解决 |
| 陷阱 25 | poll 候选筛选 vs Agent 深度分析职责边界 → 本文档附录 B 明确定义 |
| **新增 陷阱 26** | SQLite 缓存未刷新 → poll/Agent 使用过昨日 K线判断 → 每日开盘前必须确认 pre_fetch 成功 |

### 附录 E：职责边界（poll vs Agent vs 预拉取）

| 检测项 | pre_fetch (06:30) | poll 层 (5min) | Agent 层 (按需) |
|--------|-------------------|---------------|----------------|
| 日K数据获取 | ✅ 批量拉取写入 SQLite | ❌ 只读 SQLite | ✅ 优先读 SQLite，miss 则补 |
| 分时数据获取 | ❌ | ❌ | ✅ 按需实时拉 |
| 实时行情获取 | ❌ | ✅ 每5分钟拉 | ✅ 分析时 snapshot |
| 价格区间检测 | ❌ | ✅ | ✅（复核） |
| 缩量止跌 | ❌ | ✅ 读 SQLite 计算 | ✅ 深度验证 |
| 均线位置 | ❌ | ✅ 读 SQLite 计算 | ✅ 深度验证 |
| 放量阳线 | ❌ | ❌ | ✅ 本地K线+实时价格 |
| 板块联动 | ❌ | ❌ | ✅ sector_data |
| 赔率计算 | ❌ | ❌ | ✅ 强制 >= 2:1 |

---

> **下一步**：用户确认设计方向后，按 Phase 0 → 1 → 2 → 2.5 → 3 → 4 顺序实施。
> **Phase 0（K线缓存基础设施）是 v1.2 新增，建议优先实施**，因为它是后续所有 K线相关功能的基础。
