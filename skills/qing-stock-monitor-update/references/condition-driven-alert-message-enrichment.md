# 条件驱动轮询消息丰富化

## 背景

`evaluate_position_alerts()` 在 `stock_monitor.py` 中检测到价格进入 add_zone/reduce_zone/risk_zone 时输出 `RuleAlert`。初始实现的消息格式简陋：

```
加仓观察：万泽股份(000534) 当前价=30.8 涨跌幅=-2.1%；进入预设加仓区30.5-31.0。
逻辑没变、赔率变好，考虑加仓。
```

文档目标格式：

```
【机会触发】万泽股份 30.8（-2.1%）进入 add_zone 30.5-31.0
赔率3:1，UP:燃气轮机回调即是买点。止损30
```

## 实现模式

### 1. 构建 entry_points 代码映射表

```python
def _norm_code(raw: str) -> str:
    """统一 code 格式：sh603920 / sz002463 / 000425.SZ / 603920 → '603920'"""
    c = raw.lower().strip().replace('.sh', '').replace('.sz', '')
    if c.startswith('sh') or c.startswith('sz'):
        c = c[2:]
    return c

entry_by_code: dict[str, dict] = {}
for ep in config.strategy_pack.get("entry_points", []):
    ep_code = _norm_code(str(ep.get("code", "")))
    if ep_code:
        entry_by_code[ep_code] = ep
```

代码源有三种格式：
| 来源 | 示例 | 说明 |
|------|------|------|
| positions.yaml | `600246.SH` | 带 .SH/.SZ 后缀 |
| strategy_pack.yaml entry_points | `sh603920`、`sz002463` | 字母前缀 |
| 部分旧条目 | `000425.SZ`、`605060.SH` | 后缀格式 |

`_norm_code()` 同时处理前缀和后缀→裸 6 位数字。

### 2. 丰富提醒消息

```python
def _enrich_summary(action_label: str, row: dict, trigger: str,
                     latest: float, pct_change: str) -> str:
    code = str(row.get("code", ""))
    name = str(row.get("name", ""))
    norm = _norm_code(code)
    entry = entry_by_code.get(norm)
    risk_zone_raw = row.get("risk_zone") or row.get("risk_line", "")

    parts = [f"【{action_label}】{name}({code}) {latest:g}（{pct_change}%）{trigger}"]

    if entry:
        odds = entry.get("odds_analysis", "")
        cb_id = entry.get("claim_basis", "")
        if odds:
            odds_short = odds[:120] + ("…" if len(odds) > 120 else "")
            parts.append(f"赔率：{odds_short}")
        if cb_id:
            parts.append(f"参考：{cb_id}")

    if risk_zone_raw:
        parts.append(f"止损：{risk_zone_raw}")

    return " | ".join(parts)
```

### 3. 三个触发场景

| alert 类型 | action_label | severity |
|------------|-------------|----------|
| 进入减仓区 | `减仓观察` | `observe` |
| 触及风险线 | `风控观察` | `risk` |
| 进入加仓区 | `机会触发` | `opportunity` |

加仓区使用「机会触发」以匹配文档示例格式；减仓/风控保持中性标签。

### 4. 消息长度控制

- `odds_analysis` 截断到 120 字（原字段常为 80-200 字的长文分析）
- 微信提醒通常 3-5 行，适合手机端阅读
- 使用 `|` 分隔各部分，行内紧凑排版

## 关键文件

- `src/qing_investment/stock_monitor.py` — `evaluate_position_alerts()` 函数（第 223-310 行）
- `config/stock_monitor/strategy_pack.yaml` — `entry_points` 数据源
- `config/stock_monitor/positions.yaml` — 持仓数据（add_zone/risk_zone）

## 关联陷阱

见 `qing-stock-monitor-update` SKILL.md 陷阱 14「条件驱动轮询未部署」——该陷阱记录了纯规则轮询管道从无到有的过程，本参考是消息格式的具体实现。
