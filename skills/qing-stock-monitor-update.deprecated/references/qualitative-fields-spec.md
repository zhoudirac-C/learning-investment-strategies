# 描述型字段规范（Qualitative Fields Spec）

> 用途：为无法量化的市场信息提供结构化描述，供大模型在量化信号不足时做判断。
> 适用文件：watchlist.yaml、strategy_pack.yaml、positions.yaml

---

## 设计原则

1. **不替代量化字段**：`buy_setup`、`risk_line` 等量化规则继续存在，描述型字段是补充。
2. **大模型可读**：用自然语言描述，但结构固定，避免自由发挥导致解析困难。
3. **可空**：所有描述型字段均可为空，不强制填写。
4. **版本兼容**：新增字段不影响 stock_monitor.py 现有解析逻辑。

---

## 字段清单

### 1. up_mention_status（UP 提及状态）

**用途**：追踪博主最近是否提及该标的、提及语境、有无明确操作指令。

```yaml
up_mention_status:
  last_mentioned_date: "2026-05-28"           # 最近一次提及日期
  mention_context: "博主在复盘视频中提到..."    # 提及场景简述
  explicit_operation: null                     # 明确操作指令（买/卖/持有/规避）
  sentiment: "积极观察"                        # 枚举：积极观察 / 中性提及 / 明确规避 / 未提及
```

**使用场景**：
- 持仓标的很久没被提及 → 触发技术推断流程
- 观察池标的新被提及 → 更新 mention_context，可能提升 priority
- 明确规避 → 直接加入 invalidation_setup

---

### 2. technical_narrative（技术形态描述）

**用途**：用文字描述当前技术形态，弥补纯价格数字无法表达的语境。

```yaml
technical_narrative:
  trend: "5日线上方运行，短期多头排列"
  volume_character: "近3日缩量整理，今日放量突破"
  key_levels:
    - "支撑位：15.8（前低+20日均线）"
    - "压力位：18.5（前高+筹码密集区）"
  pattern: "杯柄形态右侧，等待突破确认"
  note: "长上影线显示上方抛压，需观察次日承接"
```

**使用场景**：
- 无 UP 明确买点时，大模型基于 `pattern` + `key_levels` 推断合理介入区间
- `volume_character` 帮助判断放量是健康突破还是诱多
- `note` 记录异常信号（如长上影线、跳空缺口）

---

### 3. sector_narrative（板块语境描述）

**用途**：描述标的所属板块的相对强弱、资金流向、催化与风险。

```yaml
sector_narrative:
  relative_strength: "板块今日涨幅第3，强于大盘"
  money_flow: "主力资金连续3日净流入"
  leader_follower: "跟风品种，龙头为XX"
  catalyst: "英飞凌涨价公告催化"
  risk: "板块内部分化，后排已掉队"
```

**使用场景**：
- 判断 `buy_setup` 中"组内联动"条件是否满足
- 识别板块风险（如后排掉队、龙头独木难支）
- 发现新催化，可能触发新增观察池标的

---

### 4. market_context（市场环境描述）

**用途**：记录当日/当前市场环境，影响所有标的的判断。

```yaml
market_context:
  cycle_stage: "情绪拐点确认期，非主升"
  liquidity: "缩量2704亿，存量博弈"
  style: "偏小盘成长，防御板块走弱"
  external_risk: "美股科技股晚间承压，需观察次日传导"
```

**使用场景**：
- 写入 strategy_pack.yaml 的 `today_snapshot`，供所有标的共享
- 大模型据此调整仓位建议（如缩量环境降低预期）
- `external_risk` 影响次日开盘判断

---

### 5. inference_note（推断备注）

**用途**：当 UP 未明确提及、由技术/市场推断产生操作建议时，必须标注推断依据和可靠性。

```yaml
inference_note:
  basis: "UP未明确提及，基于技术框架推断"
  confidence: "中"                             # 高 / 中 / 低
  key_assumption: "假设大盘不跌破4055"
  invalidation: "若放量跌破15.8，推断失效"
  suggested_action: "等回踩15.8-16.0区间企稳后轻仓试探"
```

**使用场景**：
- 持仓标的 UP 很久没提 → 基于技术推断操作建议，但必须标注 `basis`
- 观察池标的无 UP 买点 → 由技术框架生成 `suggested_action`
- `confidence` 指导仓位大小（高 confidence 可给正常仓位，低 confidence 只观察）

---

## 字段优先级与覆盖规则

> ⚠️ 以下优先级体系为 Agent prompt 中的判断框架，非代码强制执行。实际执行时 Agent 参考此优先级进行推理。

| 优先级 | 信号来源 | 字段 |
|--------|---------|------|
| 1（最高） | UP 明确操作指令 | `up_mention_status.explicit_operation` |
| 2 | UP 提及语境 | `up_mention_status.mention_context` |
| 3 | 量化规则触发 | `buy_setup`、`risk_line`、`invalidation_setup` |
| 4 | 技术形态推断 | `technical_narrative` + `inference_note` |
| 5（最低） | 市场环境参考 | `market_context`、`sector_narrative` |

**规则**：
- 优先级 1 存在时，直接执行，不需要推断。
- 优先级 1 不存在、优先级 2 存在时，结合量化规则判断。
- 优先级 1-2 都不存在时，才启用技术推断（优先级 4）。
- 优先级 5 始终作为背景参考，不单独触发操作。

---

## 与 stock_monitor.py 的兼容性

- 所有新增字段均为 YAML 的嵌套 dict/list，不影响现有扁平字段解析。
- `stock_monitor.py` 的 `position_rows()`、`watchlist_stock_rows()` 使用 `dict(stock)` 拷贝，不会报错。
- 新增字段默认不会被现有规则引擎读取，但会在 `format_analysis_context()` 和 `format_agent_analysis_context()` 中输出给大模型。

---

## 更新时机

| 字段 | 更新触发 | 更新者 |
|------|---------|--------|
| `up_mention_status` | 每次 qing-learning 处理新 raw 后 | Agent（检查 claims/wiki） |
| `technical_narrative` | 每次获取实时行情后 | Agent（基于 K 线数据 + 技术分析手动填写，非脚本自动生成） |
| `sector_narrative` | 每次获取实时行情后 | Agent（基于板块数据手动填写） |
| `market_context` | 每次获取实时行情后 | Agent（基于指数数据手动填写） |
| `inference_note` | 当 UP 未提及、需技术推断时 | Agent（基于以上字段综合判断） |

> ⚠️ 以上字段均为 Agent 手动维护，当前无脚本自动填充。更新时参考 `references/entry-points-generation.md` 的技术分析方法。
