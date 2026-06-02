# Curl-based K-line Fetch and Text Chart Generation

> When `run_glm_fetch.py` fails due to missing dependencies (matplotlib, akshare, yfinance, tushare), use curl + 腾讯财经 API to fetch K-line data and generate text-based charts for analysis.

## Quick Fetch

```bash
# Daily K-line (前复权)
curl -s "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz000969,day,2026-05-20,2026-06-02,100,qfq" | python3 -c "
import sys, json
d = json.load(sys.stdin)
data = d['data']['sz000969']['qfqday']
for x in data:
    print(f'{x[0]}: 开{x[1]} 高{x[2]} 低{x[3]} 收{x[4]} 量{x[5]}')
"

# Real-time quote
curl -s "https://qt.gtimg.cn/q=sz000969" | iconv -f gb2312 -t utf-8
```

## Text-based K-line Chart (Python)

When matplotlib is unavailable, generate a text chart from fetched data:

```python
import json

def text_kline_chart(klines, width=60):
    '''
    klines: list of [date, open, high, low, close, volume]
    Returns ASCII chart string
    '''
    # Extract closes for scaling
    highs = [float(x[2]) for x in klines]
    lows = [float(x[3]) for x in klines]
    max_p, min_p = max(highs), min(lows)
    range_p = max_p - min_p if max_p != min_p else 1
    
    lines = []
    lines.append(f"Price range: {min_p:.2f} - {max_p:.2f}")
    lines.append("=" * width)
    
    for x in klines:
        date, o, h, l, c, v = x
        o, h, l, c = float(o), float(h), float(l), float(c)
        # Scale to chart width
        h_pos = int((h - min_p) / range_p * (width - 1))
        l_pos = int((l - min_p) / range_p * (width - 1))
        o_pos = int((o - min_p) / range_p * (width - 1))
        c_pos = int((c - min_p) / range_p * (width - 1))
        
        bar = [' '] * width
        for i in range(min(h_pos, l_pos), max(h_pos, l_pos) + 1):
            bar[i] = '│'
        bar[o_pos] = '┤' if o > c else '├'
        bar[c_pos] = '┘' if c < o else '┐'
        
        color = '+' if c >= o else '-'
        lines.append(f"{date} {color} {''.join(bar)} {c:.2f}")
    
    return '\n'.join(lines)
```

## Anti-loop Checklist

When fetching data fails or repeats:
- [ ] After 3 identical curl attempts, STOP and assess: do I already have usable data?
- [ ] If script fails due to missing deps, switch to curl fallback immediately — don't retry the script
- [ ] If data is fetched, proceed to ANALYSIS — don't fetch again "just to be sure"
- [ ] If user asks for 分时图 and plotting libs are unavailable, offer text-based summary + key levels instead

## Key Levels Extraction

From K-line data, compute and report:
- 阶段高点/低点（5日、10日）
- 今日开盘/最高/最低/现价 vs 昨日收盘
- 成交量变化（今日 vs 昨日 vs 5日均量）
- 距成本线/风控线的距离

Example output format:
```
安泰科技 000969.SZ
├── 成本: 24.136  现价: 21.88  浮亏: -9.3%
├── 5日高点: 26.17(5/28)  5日低点: 21.11(5/21)
├── 今日: 开22.39 高? 低21.85 现21.88  量?万手
├── 关键位: 风控线21.50-22.00  减仓线22.50
└── 趋势: 5/28见顶26.17后连续下跌，今日低开跌破昨日低点
```
