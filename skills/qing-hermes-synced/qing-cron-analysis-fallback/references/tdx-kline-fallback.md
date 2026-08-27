# TDX K线直连降级方案（路径 E）

## 适用场景

当所有 HTTP API 降级路径（AKShare → EastMoney HTTP → Sina → Tencent）全部失败时，**TDX `get_kline` 可能是唯一可靠的数据源**。它直连通达信行情端口（`pytdx`），零 HTTP 依赖，不受 EastMoney 限流影响。

2026-07-28 实际验证：主脚本超时（300s），Tencent 也未成功，**但 TDX `get_kline` 直接成功返回**5个交易日日K+当日1分钟K线。

## 关键 API

```python
from src.qing_investment.tdx_market.market import TdxMarket
mkt = TdxMarket()

# 日K线（近期趋势参照）
kl_daily = mkt.get_kline('999999', count=5, category=9)
# → 日线: open/close/high/low/volume/amount/date

# 1分钟K线（实时日内走势）
kl_1min = mkt.get_kline('999999', count=240, category=8)
# → 1分钟: open/close/high/low/volume/datetime（含时分）

# 5分钟K线（盘中节奏）
kl_5min = mkt.get_kline('999999', count=48, category=1)
# → 5分钟: 同上
```

## Category 编码速查

| category | 周期 | 典型 count | 用途 |
|----------|------|-----------|------|
| 1 | 5分钟 | 48（4小时） | 盘中期指节奏 |
| 8 | 1分钟 | 240（4小时） | 精确日内走势，含午盘 13:00 分割 |
| 9 | 日线 | 5-20 | 近期趋势参考和量能对比 |

## 核心用法模式

### 模式1：今日大盘实时走势（1分钟K线）

```python
kl = mkt.get_kline('999999', count=240, category=8)
morning = [x for x in kl if x['datetime'] <= '2026-07-28 11:30']
afternoon = [x for x in kl if x['datetime'] >= '2026-07-28 13:00']

# 早盘: O/open, H/high, L/low, C/last_close
o = morning[0]['open']
h = max(x['high'] for x in morning)
l = min(x['low'] for x in morning)
c = morning[-1]['close']
chg = (c/o - 1)*100

# 午盘前15分钟(13:00-13:15)
aft_15 = [x for x in afternoon if x['datetime'] <= '2026-07-28 13:15']
aft_chg = (aft_15[-1]['close'] / afternoon[0]['open'] - 1)*100
```

### 模式2：今日量能对比（日K线）

```python
kl = mkt.get_kline('999999', count=5, category=9)
for x in reversed(kl):
    d = x['date']
    v = x.get('volume',0)/1e8   # 亿股
    a = x.get('amount',0)/1e8   # 亿元
    print(f'{d}: {x["close"]:.0f} 额{a:.0f}亿')
```

### 模式3：核心个股走势（5分钟K线）

```python
stocks = ['000938', '001258', '603407', '002409']
for code in stocks:
    kl = mkt.get_kline(code, count=48, category=1)
    first = kl[0]
    last = kl[-1]
    o,c,h,l = first['open'], last['close'], max(x['high'] for x in kl), min(x['low'] for x in kl)
    chg = (c/o - 1)*100
    # 午盘后走势
    aft = [x for x in kl if '13:' in x['datetime']]
    aft_chg = (aft[-1]['close'] / aft[0]['open'] - 1)*100 if aft else 0
    print(f'{code}: {c:.2f} O{o:.2f} H{h:.2f} L{l:.2f} {chg:+.2f}% 午盘{aft_chg:+.2f}%')
```

## 数据坑位

### 坑1（已修复/环境下依赖）：`get_quote()` 在交易时段可能返回 stale 数据

**2026-07-30 更新**：坑1已被证实在当前环境和交易时段**不再成立**。2026-07-30 09:51（交易时段）实测 `get_quote('999999')` 返回 price=3833.39（当前真实价格），与 prev_close=3828.47 不同，涨跌幅正确。该坑可能是特定环境/网络/时段依赖的历史问题，现已被修复。

```python
# ✅ 2026-07-30 09:51 已验证：get_quote 在交易时段返回真实价格
q = mkt.get_quote('999999')
# price=3833.39, prev_close=3828.47, pct_change=+0.13%
```

**注意**：如未来某时段在交易时段 `get_quote()` 再次返回 `price == prev_close`，切换 `get_kline(category=8)` 做1分钟K线分析作为备选。

### 坑2：`get_intraday()` 返回原始值，需除 1000

```python
intra = mkt.get_intraday('999999')
raw = intra[-1]['price']  # e.g. 5123494
price = raw / 1000        # → 5123.49
```

### 坑3：`get_block_info()` 返回 20 万+ 条记录，不可直接用

```python
blk = mkt.get_block_info()  # ❌ 返回 212793 条，完全不可用
```
板块排行数据只能用 AKShare（`stock_board_industry_summary_ths()`）或 Sina 端点获取。

### 坑4：TDX 不返回个股名称

`get_kline()` 返回的 dict 没有 `name` 字段。个股名称需要通过外部映射或 `get_quote()` 的 `name` 字段获取（但 `get_quote()` 在交易时段也有坑1的问题）。

## 参考实现

SKILL.md 中「午后窗口」优化部分引用了路径 E 作为 Tencent 失败后的备选方案。实际部署时请确保：

1. `pytdx` 已安装：`.venv/bin/pip install pytdx`
2. TDX 服务器可达：`180.153.18.170:7709`（2026-07-21 验证）
3. 项目代码目录已添加到 Python path，或从 `~/learning-investment-strategies` 运行
