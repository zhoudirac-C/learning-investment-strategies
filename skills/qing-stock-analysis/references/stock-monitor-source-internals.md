# stock_monitor.py 源码深度解析

> 用途：当需要理解监控脚本内部机制、排查提醒来源、修改触发逻辑时参考。
> 生成方式：通过直接阅读 `src/qing_investment/stock_monitor.py` 源码（~1800行）提取。
> 对应源码版本：以实际文件为准，本参考基于 2026-06-04 版本。

## 文件位置

```
src/qing_investment/stock_monitor.py
```

## 核心数据流

```
cron 触发 / 手动触发
    ↓
main() → build_parser() 解析 CLI 参数
    ↓
load_monitor_config() 加载三个 YAML + state.json
    ↓
run_tick()
        ├── is_a_share_trading_time() 交易时段检查
        ├── fetch_quotes_with_fallback() 拉取行情
        │       ├── fetch_eastmoney_quotes() 东方财富（主）
        │       │       └── _fetch_eastmoney_quote_chunk() HTTP 请求
        │       │       └── _fetch_eastmoney_quote_chunk_with_curl() curl 兜底
        │       └── fetch_tencent_quotes() 腾讯财经（备用）
        ├── evaluate_monitor_alerts() 评估所有规则
        │       ├── evaluate_position_alerts() 持仓风控
        │       ├── evaluate_market_alerts() 指数/市场
        │       └── evaluate_sector_rotation_alerts() 板块轮动
        ├── filter_new_alerts() 去重过滤
        ├── find_agent_analysis_trigger() 判断是否触发AI分析
        │       ├── 事件驱动：new_alerts 非空 + 今日未分析过
        │       └── 定时驱动：当前时间在 agent_analysis_schedule 中
        └── format_agent_analysis_context() 生成大模型分析上下文
```

## 关键函数详解

### 1. 行情获取

#### `fetch_quotes_with_fallback(targets)`
- 先尝试东方财富，失败则回退到腾讯
- 东方财富失败判定：`em_errors` 非空 或 `len(em_quotes) < len(targets)`
- 腾讯编码：GBK，需 `decode('gbk', errors='replace')`

#### `fetch_eastmoney_quotes(targets, timeout=8.0)`
- URL: `https://push2.eastmoney.com/api/qt/ulist.np/get`
- 参数：`fltt=2`, `invt=2`, `fields=...`, `secids=...`
- 自动分块：`QUOTE_CHUNK_SIZE`（默认可能 60-80）
- 自适应降级：`_fetch_eastmoney_quote_chunk_adaptive()` 在错误时二分拆分重试

#### `fetch_tencent_quotes(targets)`
- URL: `https://qt.gtimg.cn/q=`
- 支持批量，~60只/批次
- 返回格式：`v_sh600246="1~万通发展~600246~..."`
- 字段分隔符：`~`
- 关键字段索引：
  - `parts[1]` = 名称
  - `parts[2]` = 代码
  - `parts[3]` = 最新价
  - `parts[4]` = 昨收
  - `parts[5]` = 开盘
  - `parts[33]` = 最高
  - `parts[34]` = 最低
  - `parts[37]` = 成交额（如有）
- **涨跌幅计算**：必须手动 `(latest - prev) / prev * 100`，不要硬编码索引

### 2. 规则评估

#### `evaluate_position_alerts(config, quotes, current_time)`
遍历 `positions.yaml` 中的每个持仓：

| 条件 | 触发动作 | 字段来源 |
|------|---------|---------|
| `latest` 落入 `reduce_zone` | 减仓观察 | `positions.yaml` |
| `latest <= risk_zone[1]` | 风控观察 | `risk_zone` 优先，`risk_line` fallback |

**`parse_price_zone()` 解析规则**：
- `"41.15-42.5"` → `(41.15, 42.5)`
- `44.5`（单点数值）→ `(44.5, 44.5)`
- 因此 `risk_line: 44.5` 实际触发条件为 `latest <= 44.5`

#### `evaluate_market_alerts(config, quotes, current_time)`
检查 `strategy_pack.yaml` 中 `market_framework.index_rules`：
- 支持 `trigger_condition: close_below`（通用格式）
- 支持 legacy 格式：`trend_defense: 1750`
- **已知限制**：`valid_close_level` 和 `weak_close_level` 仅在 interpretation 文本中描述，代码可能未实现中间档位主动提醒

#### `evaluate_sector_rotation_alerts(config, quotes, current_time)`
计算 `offensive_groups` 和 `defensive_groups`：
- `pct_spread = offensive_avg_pct - defensive_avg_pct`
- `red_ratio_spread = offensive_red_ratio - defensive_red_ratio`
- 进攻回流：`pct_spread >= min_spread_pct` 且 `red_ratio_spread >= min_red_ratio_spread`
- 防御切换：`-pct_spread >= min_spread_pct` 且 `-red_ratio_spread >= min_red_ratio_spread`
- **关键**：若两组差值均未达阈值，**不触发任何提醒**

### 3. 去重机制

#### `filter_new_alerts(alerts, state, value, dedupe_minutes=30)`
- 指纹生成：`alert_fingerprint()` → `"action|stock_code|stock_name|trigger"`
- 状态存储：`state.json` 的 `alert_history` 字段
- **重要**：指纹包含完整 `trigger` 文本，因此 `"触及风险线44.5"` 和 `"触及风险线44.5-45.5"` 视为不同指纹

#### `record_alert_decision_log(state, alerts, emitted_alerts, value)`
- 记录所有 alert 的决策（emitted/suppressed）
- 存储在 `state.json` 的 `alert_decision_log` 中
- 用于收盘复盘分析

### 4. AI 分析触发

#### `find_agent_analysis_trigger(config, state, value, alerts)`
两种触发方式：

**事件驱动**：
- `alerts` 非空
- 生成 fingerprint 组合：`"event:{date}:{fingerprints}"`
- 若今日未分析过该组合 → 触发

**定时驱动**：
- 遍历 `agent_analysis_schedule_rows(config)`
- 匹配当前时间 `HH:MM`
- 生成 dedupe_key：`"scheduled:{id}:{date}"`
- 若今日未触发过 → 触发

#### `format_agent_analysis_context(config, value, trigger, alerts, quote_snapshot, state)`
生成 `[Hermes股票监控大模型分析上下文]`，包含：
1. 触发类型、触发点、触发原因
2. 当前框架 + 核心问题
3. 规则信号列表
4. 状态摘要（alert_count, risk_count, sector_actions）
5. 板块连续信号（sector_signal_counts）
6. 实时行情快照（前30条）
7. **格式化指令**：固定模板要求（盘面→持仓池→观察池→脚注，≤450字）

### 5. 状态文件结构

`state.json` 核心字段：

```json
{
  "version": 1,
  "last_updated": "2026-06-04T09:52:53+08:00",
  "alert_history": {
    "action|stock_code|stock_name|trigger": "2026-06-04T09:30:00+08:00"
  },
  "alert_decision_log": [
    {
      "date": "2026-06-04",
      "time": "2026-06-04T09:30:00+08:00",
      "status": "emitted|suppressed",
      "fingerprint": "...",
      "action": "减仓观察",
      "stock_code": "000969.SZ",
      "stock_name": "安泰科技",
      "price": 25.79,
      "severity": "risk|observe",
      "trigger": "触及或跌破风险线21.00-21.50",
      "summary": "安泰科技(000969.SZ) 触及或跌破风险线21.00-21.50，最新价25.79"
    }
  ],
  "sector_signal_counts": {
    "action|stock_code|stock_name|trigger": {
      "action": "进攻回流观察",
      "count": 3,
      "last_seen_at": "2026-06-04T09:30:00+08:00"
    }
  },
  "last_market_state": {
    "time": "...",
    "quote_count": 146,
    "alert_count": 5,
    "risk_count": 2,
    "observe_count": 3,
    "sector_actions": ["进攻回流观察"]
  },
  "last_quote_snapshot": {...},
  "last_fetch_error": {...},
  "agent_analysis_history": {
    "scheduled:open:2026-06-04": {
      "time": "...",
      "kind": "scheduled",
      "id": "open",
      "title": "开盘观察",
      "reason": "隔夜消息+开盘方向确认"
    }
  }
}
```

## CLI 参数速查

| 参数 | 作用 |
|------|------|
| `--status` | 打印监控配置状态 |
| `--smoke` | 打印测试通知 |
| `--emit-status-on-tick` | 交易时段内即使无触发也输出状态 |
| `--ignore-trading-time` | 绕过交易时段检查（测试用） |
| `--analysis-context` | 输出分析上下文（无行情） |
| `--live-analysis-context` | 输出分析上下文（带实时行情） |
| `--daily-review-context` | 输出收盘复盘上下文 |
| `--agent-context-on-trigger` | 触发时输出大模型分析上下文 |
| `--dedupe-minutes N` | 去重窗口（默认30分钟） |
| `--state-file PATH` | 指定状态文件路径 |

## 配置加载顺序

`load_monitor_config(config_dir)`：
1. `positions.yaml`（优先）或 `positions.example.yaml`（fallback）
2. `watchlist.yaml`
3. `strategy_pack.yaml`

## 常见排查命令

```bash
# 查看监控配置状态
python -m qing_investment.stock_monitor --status

# 查看带实时行情的分析上下文
python -m qing_investment.stock_monitor --live-analysis-context

# 查看收盘复盘上下文
python -m qing_investment.stock_monitor --daily-review-context

# 测试触发（非交易时段）
python -m qing_investment.stock_monitor --ignore-trading-time --agent-context-on-trigger

# 缩短去重窗口测试
python -m qing_investment.stock_monitor --dedupe-minutes 15

# 查看 state.json 结构
python3 -c "import json; print(json.dumps(json.load(open('config/stock_monitor/state.json')), indent=2, ensure_ascii=False))"
```

## 与 qing-stock-analysis SKILL.md 的关系

本文件是源码级别的技术参考，SKILL.md 中的"监控脚本内部机制"章节是面向分析的用法参考。两者互补：
- 需要**修改触发逻辑/排查bug** → 读本文件
- 需要**理解提醒行为/复盘分析** → 读 SKILL.md 监控章节
