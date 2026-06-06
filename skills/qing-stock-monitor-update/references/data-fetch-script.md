# 数据获取脚本规范

> 脚本路径：`skills/qing-stock-monitor-update/scripts/fetch_stock_data.py`
> 目标：为 watchlist + positions 中的所有标的获取实时/近期数据，输出结构化 JSON 供 LLM 分析。

---

## 数据源优先级（与 qing-stock-analysis 一致）

1. **运行环境原生金融数据能力**（如有）
2. **东方财富实时行情**（stock_monitor.py 已有接口）
3. **glmv-stock-analyst/fetch_all.py**（K线、基本面、主力资金、分时图）
4. **新浪财经/其他公开接口**（降级）

---

## 输出数据结构

```json
{
  "meta": {
    "fetch_time": "2026-05-31 14:30:00 CST",
    "data_source": "eastmoney_push2 + glmv_fetch",
    "degraded": false,
    "missing_fields": []
  },
  "market": {
    "indexes": {
      "上证指数": {"latest": 4098.64, "pct_change": 0.12, "volume": "..."},
      "深证成指": {...},
      "创业板指": {...}
    },
    "context": {
      "cycle_stage": "情绪拐点确认期",
      "liquidity": "缩量2704亿",
      "style": "偏小盘成长"
    }
  },
  "stocks": [
    {
      "code": "600246.SH",
      "name": "万通发展",
      "latest": 16.81,
      "open": 15.50,
      "high": 16.81,
      "low": 15.30,
      "close": 16.81,
      "pct_change": 10.01,
      "volume": 1234567,
      "amount": 20789012,
      "prev_close": 15.28,
      
      "kline": {
        "ma5": 15.20,
        "ma10": 14.80,
        "ma20": 14.50,
        "rsi14": 68.5,
        "macd_signal": "金叉"
      },
      
      "capital_flow": {
        "main_net_inflow": 5200000,
        "main_net_inflow_pct": 25.0,
        "consecutive_days": 2,
        "direction": "主力净流入"
      },
      
      "technical_narrative": {
        "trend": "5日线上方运行，短期多头排列",
        "volume_character": "涨停放量，量能健康",
        "key_levels": ["支撑：15.0（涨停开盘价）", "压力：17.5（前高）"],
        "pattern": "突破平台后首板",
        "note": "封单坚决，无开板"
      },
      
      "sector_narrative": {
        "relative_strength": "CPU自研链最强标的",
        "money_flow": "主力资金连续2日净流入",
        "leader_follower": "板块龙头",
        "catalyst": "字节自研CPU催化",
        "risk": "组内分化，得润大跌"
      },
      
      "sector_positioning": {
        "up_position": "UP知识库中的标注（如有）",
        "final_position": "综合UP标注和实时数据的最终定位",
        "final_reason": "判断依据",
        "sector_details": [
          {
            "sector_name": "华为汽车",
            "rank": "1/97",
            "changepercent": 10.01,
            "mktcap": 81.02,
            "turnoverratio": 6.40,
            "position_tag": "日内龙头"
          }
        ]
      },
      
      "charts": {
        "kline_daily": "/path/to/kline_600246.png",
        "intraday": "/path/to/intraday_600246.png",
        "capital_flow": "/path/to/capital_600246.png"
      }
    }
  ]
}
```

---

## 降级规则

| 场景 | 降级行为 | 标记 |
|------|---------|------|
| 东方财富超时 | 尝试新浪财经接口 | `data_source: "sina_fallback"` |
| K线数据缺失 | 只输出实时行情 | `missing_fields: ["kline"]` |
| 主力资金缺失 | 跳过该字段 | `missing_fields: ["capital_flow"]` |
| 分时图下载失败 | 跳过图表 | `missing_fields: ["intraday_chart"]` |
| 全部数据源失败 | 输出空数据 + 错误信息 | `degraded: true` |

---

## 命令行接口

```bash
# 获取观察池 + 持仓的所有标的数据
python3 skills/qing-stock-monitor-update/scripts/fetch_stock_data.py \
  --config-dir config/stock_monitor \
  --output /tmp/stock_data_$(date +%Y%m%d_%H%M).json

# 只获取指定标的
python3 skills/qing-stock-monitor-update/scripts/fetch_stock_data.py \
  --codes 600246.SH,002055.SZ \
  --output /tmp/stock_data.json

# 包含龙虎榜数据（如有）
python3 skills/qing-stock-monitor-update/scripts/fetch_stock_data.py \
  --config-dir config/stock_monitor \
  --include-lhb \
  --output /tmp/stock_data.json
```

---

## 与 stock_monitor.py 的集成

- `fetch_stock_data.py` 独立运行，不依赖 stock_monitor.py 的内部状态。
- 输出 JSON 可被 stock_monitor.py 的 `format_live_analysis_context()` 读取，追加到分析上下文中。
- 图表路径写入 JSON，大模型分析时可引用查看。
