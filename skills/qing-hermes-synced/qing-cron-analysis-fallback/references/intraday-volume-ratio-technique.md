# 日内量能比率分析法（Tencent Finance，2026-08-26 验证）

## 适用场景

当 AKShare/EastMoney 不可用（cron 脚本超时降级）时，用 Tencent Finance API 快速产出"今日量能 vs 昨日量能"对比，为 14:50 尾盘监控报告提供量能判断依据。

## 核心原理

Tencent 实时端点（`qt.gtimg.cn`）返回的 `parts[36]` 是**截至当前时刻的累计成交量（手）**，即当日已产生总量。Tencent K线端点（`web.ifzq.gtimg.cn`）返回历史每日成交量。两者直接相除得到**量比**。

## 关键公式

```
量比 = 今日已产生成交量 / 昨日全天成交量
```

| 量比区间 | 定性 |
|----------|------|
| < 80% | 明显缩量 |
| 80-95% | 缩量 |
| 95-105% | 持平/微放微缩 |
| 105-120% | 温和放量 |
| 120-150% | 明显放量 |
| > 150% | 剧烈放量 |

## 数据采集流程

### Step 1：获取今日实时行情（含累计成交量）

```python
import urllib.request, json

codes = ["sh000001","sz399001","sz399006","sh000688","sh000300","sh000016"]
url = f"https://qt.gtimg.cn/q={','.join(codes)}"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as resp:
    raw = resp.read().decode("gbk", errors="ignore")

for line in raw.strip().split(";"):
    parts = line.split("~")
    if len(parts) < 38: continue
    code = parts[2]
    vol = int(parts[36])  # 手
    amt = int(parts[37])  # 万元
    pct = float(parts[32])
    print(f"{code}: 涨跌幅{pct}% 量{vol:,}手 额{amt/1e4:.0f}亿")
```

### Step 2：获取昨日全天成交量（K线端点）

```python
def fetch_yesterday_volume(code):
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,5,qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode()
    data = json.loads(raw)
    inner = data["data"][code]  # 路径: data["data"][code]["day"]
    klines = inner["day"]
    # klines 按时间升序排列，klines[-2] 是昨日（klines[-1] 是今日盘中）
    # 每行 [日期, 开, 收, 高, 低, 成交量(手), 成交额(元)] 共7字段
    yesterday = klines[-2]
    return int(float(yesterday[5]))

yest_vol = fetch_yesterday_volume("sh000001")
print(f"昨日全天: {yest_vol:,} 手")
```

### Step 3：计算量比并定性

```python
ratio = today_vol / yest_vol
if ratio >= 1.2:  verdict = "明显放量"
elif ratio >= 1.05: verdict = "温和放量"
elif ratio >= 0.95: verdict = "持平/微放微缩"
elif ratio >= 0.8: verdict = "缩量"
else:  verdict = "明显缩量"
```

## ⚠️ 注意：时间窗口修正

- **9:30-11:30 上午**：量比应 ×2 估算全天（假设下午等量）
- **13:00-15:00 下午**：量比已接近全天，直接对比
- **14:50**：今日量 ≈ 全天的 95%+，量比基本等同于全天量比

## 2026-08-26 14:50 实际数据验证

| 指数 | 今日量(手) | 昨日量(手) | 量比 | 定性 |
|------|-----------|-----------|------|------|
| 上证指数 | 4.72亿 | 4.64亿 | 101.7% | 持平微放 |
| 深证成指 | 5.57亿 | 5.80亿 | 96.0% | 略缩 |
| 创业板指 | 1.59亿 | 1.71亿 | 93.0% | 缩量反弹 |
| 科创50 | 719万 | 717万 | 100.2% | 量平价涨 |
| 沪深300 | 1.78亿 | 1.72亿 | 103.8% | 温和放量 |
| 上证50 | 4384万 | 4223万 | 103.8% | 温和放量 |

**结论**：温和放量普涨，非暴力突破，结构修复型反弹。

## 常见陷阱

1. **Tencent 实时量是累计量**，不是半日/单盘量，直接与昨日全天对比即可（下午时段）
2. **K线 `day` 列表按时间升序**，昨日是 `klines[-2]`，今日盘中是 `klines[-1]`
3. **成交量字段是字符串**，需 `int(float(kline[5]))` 转换
4. **K线端点 JSON 路径是 `data["data"][code]["day"]`**，不是 `data["day"]`
