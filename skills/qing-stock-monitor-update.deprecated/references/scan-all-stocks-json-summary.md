# scan_all_stocks.py --json-summary 模式

> 2026-06-06 新增。为 agent/cron 消费提供紧凑 JSON 输出。

## 用法

```bash
cd ~/learning-investment-strategies
python scripts/scan_all_stocks.py --json-summary
```

## 输出格式

正常文本输出后，会追加 JSON 区块：

```
---JSON_SUMMARY_START---
{
  "scan_time": "2026-06-07T11:30:00",
  "total": 150,
  "buyable": [
    {
      "code": "000636.SZ",
      "name": "风华高科",
      "price": 63.5,
      "change_pct": 4.89,
      "entry_zone": "只观察不介入",
      "position_ratio": "0",
      "tech_score": 4,
      "tech_signal": "buy",
      "ma_summary": "多头排列",
      "reason": "...",
      "note": "..."
    }
  ],
  "wait": [...],
  "avoid": [...],
  "no_zone": [...],
  "no_data": [...]
}
---JSON_SUMMARY_END---
```

## 字段说明

| 字段 | 说明 |
|------|------|
| `code` | 标准化 code (sh/sz + 数字) |
| `price` | 最新价 |
| `change_pct` | 涨跌幅 % |
| `entry_zone` | 策略中的介入区间 |
| `position_ratio` | 建议仓位 |
| `tech_score` | 技术评分（-1=卖出, 0=中性, 1=买入, 2=强买入） |
| `tech_signal` | 综合信号（buy/neutral/sell） |
| `ma_summary` | 均线趋势简述 |

## 集成方式

Cron/Agent 消费时，提取 `---JSON_SUMMARY_START---` 和 `---JSON_SUMMARY_END---` 之间的内容即可：

```bash
python scripts/scan_all_stocks.py --json-summary 2>/dev/null \
  | sed -n '/---JSON_SUMMARY_START---/,/---JSON_SUMMARY_END---/p' \
  | grep -v '^---' \
  | python -c "import sys,json; print(json.dumps(json.load(sys.stdin), indent=2))"
```
