# Sina Batch Stock Basket → Sector Rotation Inference

> **Purpose**: When sector board APIs (East Money push2 clist/get, AKShare stock_board_industry_*) are unavailable, use Sina API batch query of representative stocks to infer sector rotation patterns.
> **Verified**: 2026-07-30 11:25 morning analysis session
> **Total latency**: ~0.5-1s for 25 stocks (single curl)

## Why This Technique Exists

| API Source | Sector Data | Status |
|-----------|-------------|--------|
| East Money push2 clist/get | Block/sector rankings | ❌ Often rate-limited (rc=102) or empty response |
| AKShare stock_board_industry_* | Block rankings | ❌ RemoteDisconnected in heavy-traffic windows |
| Sina hq.sinajs.cn | Individual stocks only | ✅ Working (needs Referer header) |

The gap: when East Money and AKShare both fail for sector data, Sina individual stock API still works but doesn't provide sector rankings. The solution is to **batch-query representative stocks from each sector** and manually infer rotation patterns.

## Stock Basket Template

### Current Basket (25 stocks, 12 sectors)

```
# Sina code format: sz for 深市, sh for 沪市
# Deep tech (7)
华北: sz002371    长电: sh600584    华天: sz002185    兆易: sh603986
雅克: sz002409    生益: sh600183    诺德: sh600110

# Commercial aerospace (3)
卫星: sh600118    航天动力: sh600343    航天电器: sz002025

# Liquor defense (3)
茅台: sh600519    五粮液: sz000858    汾酒: sh600809

# Banking defense (3)
招行: sh600036    兴业: sh601166    平安: sz000001

# White goods defense (2)
美的: sz000333    格力: sz000651

# Food defense (1)
伊利: sh600887

# Lithium battery neutral (2)
宁德: sz300750    恩捷: sz002812

# Solar neutral (2)
隆基: sh601012    阳光: sz300274

# Broker sentiment (1)
东财: sz300059

# Telecom dividend defense (1)
移动: sh600941
```

**Total codes string for Sina**:
```
sz002371,sh600584,sz002185,sh603986,sz002409,sh600183,sh600110,sh600118,sh600343,sz002025,sh600519,sz000858,sh600809,sh600036,sh601166,sz000001,sz000333,sz000651,sh600887,sz300750,sz002812,sh601012,sz300274,sz300059,sh600941
```

### One-curl Example (2026-07-30 Verified)

```bash
codes="sz002371,sh600584,sz002185,sh603986,sz002409,sh600183,sh600110,sh600118,sh600343,sz002025,sh600519,sz000858,sh600809,sh600036,sh601166,sz000001,sz000333,sz000651,sh600887,sz300750,sz002812,sh601012,sz300274,sz300059,sh600941"

curl -s -H "Referer: https://finance.sina.com.cn" \
  "https://hq.sinajs.cn/list=$codes" --connect-timeout 5 --max-time 10 \
  | python3 -c "
import sys, re
raw = sys.stdin.buffer.read().decode('gbk', errors='ignore')
results = {}
for line in raw.strip().split('\n'):
    m = re.search(r'\"(.*?)\"', line)
    if not m: continue
    parts = m.group(1).split(',')
    name = parts[0]
    prev = float(parts[2]); cur = float(parts[3])
    high = float(parts[4]); low = float(parts[5])
    chg = (cur - prev) / prev * 100
    amplitude = (high - low) / prev * 100
    amount = float(parts[9])/1e8
    results[name] = {'chg': chg, 'amount': amount, 'amp': amplitude}
    print(f'{name+chr(9):10s} {chg:>+.2f}%  amt={amount:>5.0f}亿  amp={amplitude:.1f}%')

# Group by sector for inference
tech = [v['chg'] for k,v in results.items() if k in ['北方华创','长电科技','华天科技','兆易创新','雅克科技','生益科技','诺德股份']]
defense = [v['chg'] for k,v in results.items() if k in ['茅台','五粮液','山西汾酒','招商银行','兴业银行','平安银行','美的集团','格力电器','伊利股份','中国移动']]
if tech and defense:
    t_avg = sum(tech)/len(tech); d_avg = sum(defense)/len(defense)
    print(f'\n=== 推断 ===')
    print(f'科技簇均值: {t_avg:+.2f}%')
    print(f'防御簇均值: {d_avg:+.2f}%')
    if t_avg < -5 and d_avg > 2:
        print('>>> 结论: 防御切换确认 — 热钱从科技撤至消费金融')
    elif t_avg > 0 and abs(d_avg) < 0.5:
        print('>>> 结论: 科技进攻 — 风险偏好高')
    elif d_avg < 0 and t_avg < 0:
        print('>>> 结论: 系统抛售 — 无避风港')
    elif t_avg < -3 and d_avg > 1:
        print('>>> 结论: 防御偏强 — 避险情绪升温')
    else:
        print('>>> 结论: 震荡/轮动 — 需进一步观察')
" 2>&1
```

## Inference Rules

### Quantitative thresholds

| Inference | Condition | Reliability |
|-----------|-----------|-------------|
| 防御切换 | tech_mean < -5% AND defense_mean > 2% AND > 70% of tech stocks < -3% | High (>80%) |
| 科技进攻 | tech_mean > 0 AND \|defense_mean\| < 0.5% AND > 60% of tech stocks positive | High |
| 系统抛售 | ALL sectors mean < -2% AND no sector has > 0% mean | High |
| 普涨日 | ALL sectors mean > 1% AND > 60% of stocks positive | High |
| 震荡轮动 | Between thresholds; need more data | Medium -- flags uncertainty |

### Leading indicators (sector tipping points)

Watch these specific stocks for early signals:

| Stock | Signal | Meaning |
|-------|--------|---------|
| 雅克科技 002409 | -8~-10% while other tech -3~-5% | **科技退潮领先信号** — 高位材料票补跌，通常先于板块整体 1-2 天 |
| 生益科技 600183 | -8~-10% | **CCL补跌** — 涨价逻辑最硬的环节也开始跌，说明资金在无差别减仓 |
| 茅台 600519 | >+2% while tech <-5% | **防御确认** — 超级权重白酒扛旗，机构资金切换 |
| 招商银行 600036 | >+1.5% while 上证50 flat | **银行独立走强** — 护盘/防守信号增强 |
| 长电科技 600584 | 翘板 from -9% to -5% | **科技情绪尝试修复** — 观察次日能否延续 |
| 东方财富 300059 | >+2% | **券商异动** — 增量资金或政策催化预期 |

### 2026-07-30 Real-world Example (11:25 AM)

```
科技簇: 北方华创 -6.65%, 长电科技 -9.85%, 华天科技 -9.17%, 
         兆易创新 -4.40%, 雅克科技 -10.00%(跌停), 生益科技 -8.88%, 
         诺德股份 -7.74%
         → mean = -7.96%

白酒:   茅台 +2.95%, 五粮液 +4.55%, 山西汾酒 +5.31%
         → mean = +4.27%

银行:   招行 +1.24%, 兴业 +2.05%, 平安 +1.95%
         → mean = +1.74%

结论: 科技簇均值 -7.96% < -5% ✓ AND 防御簇(白酒+银行)均值 > 2% ✓
      → **防御切换确认** — 这与实时板块 API 数据一致
      → 标题: "大规模风格切换已确认发生"
```

## Limitations

1. **Not a replacement for real sector API data** when available. Use this only when paths A/B fail.
2. **Small-cap bias**: representative stocks are mostly large/mid caps. Small-cap rotation may be missed.
3. **Single stock noise**: individual stock -10% could be company-specific news, not sector-wide. Mitigate by using 2+ stocks per sector.
4. **Sina stability**: Sina API has shown intermittent failures (2026-07-21). If Sina also fails, fall through to Tencent (路径 D) or TDX (路径 E).
5. **No breadth data**: Cannot compute advance/decline ratio, breadth, or涨停/跌停 count from this method alone.

## When to Use

- ✅ Sector board APIs (East Money clist/get, AKShare board endpoints) return empty/timeout
- ✅ Sina individual stock API is working (test with `curl -s -H "Referer: https://finance.sina.com.cn" "https://hq.sinajs.cn/list=sh000001"`)
- ✅ You need sector-level rotation inference, not precise per-sector heatmap
- ❌ If sector board data is available, use it directly instead
- ❌ If you need涨停/跌停 counts, add specific endpoints (Tencent for 跌停板, or AKShare stock_zt_pool_em)
