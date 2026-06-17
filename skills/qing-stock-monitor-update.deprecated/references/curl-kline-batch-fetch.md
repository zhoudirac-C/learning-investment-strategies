# Curl K线批量拉取 + 均线速算

> 轻量替代 `scan_all_stocks.py`，适合 ad-hoc 快速技术分析，无需完整 Python 环境。

## 单行命令

```bash
for code in sz002409 sh600500 sh600378; do
  result=$(curl -s "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${code},day,,,20,qfq" | python3 -c "
import sys,json
data = json.load(sys.stdin)
code = list(data['data'].keys())[0]
klines = data['data'][code].get('qfqday', data['data'][code].get('day', []))[-20:]
closes = [float(k[2]) for k in klines if len(k) > 2]
highs = [float(k[3]) for k in klines if len(k) > 3]
lows = [float(k[4]) for k in klines if len(k) > 4]
ma5 = sum(closes[-5:])/5 if len(closes) >= 5 else 0
ma10 = sum(closes[-10:])/10 if len(closes) >= 10 else 0
ma20 = sum(closes)/len(closes) if closes else 0
high20 = max(highs); low20 = min(lows)
chg5 = (closes[-1]/closes[-6]-1)*100 if len(closes) >= 6 else 0
print(f'{closes[-1]:.2f}|{ma5:.2f}|{ma10:.2f}|{ma20:.2f}|{high20:.2f}|{low20:.2f}|{chg5:.1f}')
")
  echo "$code $result"
  sleep 0.3
done
```

## 输出格式

```
code 最新|MA5|MA10|MA20|20日高|20日低|近5日涨幅%
```

## 腾讯K线字段顺序（容易踩坑）

```
k[0]=日期, k[1]=开盘, k[2]=收盘, k[3]=最高, k[4]=最低, k[5]=成交量
```

**注意**：k[3]=最高，k[4]=最低。常见错误是反过来用，导致 low > high。

## 均线状态判断

| 状态 | 条件 | 含义 |
|------|------|------|
| 多头排列 | 最新 > MA5 > MA10 > MA20 | 趋势向上 |
| 多头回调 | MA5 > MA10 > MA20 但 最新 < MA5 | 趋势中回调 |
| 空头排列 | 最新 < MA5 < MA10 < MA20 | 趋势向下 |
| 短期多头 | 最新 > MA5 > MA10 但 MA10 < MA20 | 反弹初期 |
| 均线缠绕 | 三者交叉无方向 | 震荡 |

## 与 entry-points-generation 配套

拉取MA数据后，结合 `entry-points-generation.md` 四种方法：
1. **均线法** → 多头趋势票 → [MA5×0.97, MA5] 或 MA10附近
2. **回撤百分比法** → 已大涨票 → 基于近5日涨幅确定回撤率
3. **近期低点法** → 震荡/空头票 → [20日低×0.98, 20日低×1.02]
4. **分时低点法** → 日内回踩 → 需配合实时行情

## 注意事项

- 分批加 `sleep 0.3` 避免腾讯API限流
- `qfq` 前复权，非复权会高估回撤
- 20日K线覆盖约1个月，适合近期趋势判断
