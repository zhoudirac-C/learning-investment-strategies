# AKShare 降级可用函数速查（2026-07-20 已验证）

> 适用场景：cron 脚本超时，但 AKShare 本地库仍可用。
> 目的：提供一组**经现场验证可用的** AKShare 函数，避免重复踩坑。

## 快速验证

```bash
cd ~/learning-investment-strategies && python3 -c "
import akshare as ak
print(f'akshare version: {ak.__version__}')
"
# 输出版本号即表明可用
```

## 第一优先：`stock_zh_index_spot_em()` ✅ 最快最稳

**耗时**：~5-10s（2页爬取）
**产出**：沪市+深市所有指数的实时行情，含涨跌幅、成交额、量比

```python
import akshare as ak

df = ak.stock_zh_index_spot_em()
# 列名: ['序号','代码','名称','最新价','涨跌幅','涨跌额','成交量','成交额','振幅','最高','最低','今开','昨收','量比']

# 主要指数快速提取
target_indices = { '000001': '上证指数', '000016': '上证50', '000300': '沪深300',
                   '000905': '中证500', '000688': '科创50', '399001': '深证成指',
                   '399006': '创业板指', '399005': '中小100' }

for code, name in target_indices.items():
    row = df[df['代码'] == code]
    if len(row) > 0:
        r = row.iloc[0]
        vol_yi = r['成交额'] / 1e8
        lb = r.get('量比', 0)
        vol_label = '放量' if lb > 1.2 else ('缩量' if lb < 0.8 else '平量') if lb > 0 else 'N/A'
        print(f"{name}: {r['最新价']:.2f}  {r['涨跌幅']:+.2f}%  成交{vol_yi:.0f}亿  量比{lb:.2f}({vol_label})")
```

**关键价值**：量比数据是判断当日资金热度最直接的指标。上证50量比1.5+说明蓝筹有资金大幅流入。

## 第二优先：`stock_board_industry_summary_ths()` ✅ 同花顺行业板块排名

**耗时**：~0-2s（极快）
**产出**：56个行业板块按涨跌幅排序，含涨跌幅、净流入、上涨/下跌家数、领涨股

```python
import akshare as ak

summary = ak.stock_board_industry_summary_ths()
# 列名: ['序号','板块','涨跌幅','总成交量','总成交额','净流入','上涨家数','下跌家数','均价','领涨股','领涨股-最新价','领涨股-涨跌幅']

# TOP 涨幅
top = summary.sort_values(by='涨跌幅', ascending=False).head(10)
print("=== 行业板块 TOP 10 ===")
for _, row in top.iterrows():
    print(f"{row['板块']}: {row['涨跌幅']}%  (净流入:{row.get('净流入', 'N/A')})")

# BOTTOM 跌幅
bottom = summary.sort_values(by='涨跌幅', ascending=True).head(10)
print("=== 行业板块 BOTTOM 10 ===")
for _, row in bottom.iterrows():
    print(f"{row['板块']}: {row['涨跌幅']}%")
```

**关键价值**：同花顺的行业分类（相比东方财富）更贴近A股投资逻辑，含领涨股信息便于快速定位龙头。

## 第三优先：`stock_zh_index_daily()` ✅ 历史K线对比

**耗时**：~1-2s
**产出**：指定指数的全部日K线数据（含成交量、成交额、开高低收）

```python
import akshare as ak

sh = ak.stock_zh_index_daily(symbol="sh000001")  # 上证
# 列名: ['date','open','high','low','close','volume']

# 最近3日对比
print(sh.tail(3))
```

**注意**：`volume` 列的单位是**股数/手数**，不是人民币金额。如需成交额对比，用 `stock_zh_index_spot_em()` 的 `成交额` 列。

### 替代方案：`stock_zh_index_daily_em()`（东方财富日K，午后窗口备用）

当 `stock_zh_index_spot_em()` 在午后 14:30-15:00 窗口因限流仅返回部分指数时，用此接口按证券代码逐一补缺（早午窗口都稳定）。

```python
# sz399001=深证成指, sz399006=创业板指
df = ak.stock_zh_index_daily_em(symbol="sz399006")
last = df.iloc[-1]     # 今日（至请求时刻）
prev = df.iloc[-2]     # 昨收
change_pct = (last['close'] - prev['close']) / prev['close'] * 100
```

**⚠️ 重要**：
- `close` 是到该时刻的收盘价（非实时最新价），涨跌幅需自行计算
- 指数代码格式：深证/创业板用 `sz` 前缀；上证/科创用 `sh` 前缀
- 该接口**返回完整的日K线历史**，不是实时分时，所以响应快、不受尾盘限流影响

## ⚠️ Partial Pagination 陷阱 — `stock_zh_index_spot_em()` 分页顺序

**这个 API 按固定页码顺序爬取**，并非一次性返回所有指数。主要指数位于第1-2页，因此：

| 页码 | 内容 | 午后窗口成功率 |
|------|------|:------------:|
| 第1页 | 上证指数(000001)、科创50(000688)、沪深300(000300) 等 | ✅ 几乎总成功 |
| 第2页 | 深证成指(399001)、创业板指(399006) 等 | ⚠️ 偶发失败（午后尤甚） |
| 后续页 | 中小板、其他分类指数 | ❌ 午后窗口频繁断连 |

**关键教训**：`stock_zh_index_spot_em()` 返回的 DataFrame 中缺失了某指数代码，**不代表该接口不可用**，只代表该指数所在翻页在请求时被限流/超时了。**不要因此放弃整个接口**——第1页的指数数据仍然有效可靠。**此陷阱不限于午后**：2026-08-03 10:14（上午窗口）实测同样出现第2页缺失（深证成指/创业板指/中小100 不在返回的 268 行中）。无论哪个时段，拿到缺失列表后**先用 Tencent `qt.gtimg.cn` 批量补全缺失指数**（一次请求即可，~0.5s，100% 可靠），再决定是否重试 AKShare。

**检查方法**：
```python
indices = ak.stock_zh_index_spot_em()
got = indices['代码'].tolist()
print(f"成功获取 {len(got)} 个指数")
# 检查关键指数是否都拿到了
for code in ['000001', '399001', '399006', '000688']:
    status = '✅' if code in got else '❌ 缺失'
    print(f"  {code}: {status}")
```

## 时间窗口敏感型失败（2026-07-24 验证）

部分 API 在**午后 14:30-15:00 窗口**连接稳定性显著下降（比早盘更差），即使此前已验证可用。

### 已知的时间窗口退化模式

| 时段 | 稳定性 | 建议策略 |
|------|--------|---------|
| 09:25-09:30 | 东方财富 push2 返回 rc=102（数据未就绪） | 走 Sina/Tencent 路径 |
| 09:30-11:30 | ⚠️ 分页限流（**2026-08-03 10:14 实测**：`stock_zh_index_spot_em()` 返回 268 行但深证成指/创业板指/中小100 缺失，上证/科创50/沪深300/中证500/中证1000 正常） | 按默认优先级；**缺失指数用 Tencent `qt.gtimg.cn` 批量补**（一次请求，~0.5s，100% 可靠） |
| 13:00-14:00 | ⚠️ 偶发断连 | 单 API 重试 ≤2 次 |
| **14:30-15:00** | ❌ 频繁 ConnectionError | **优先 Tencent（路径 D）获取基础数据**，AKShare 仅用于补缺 |

### 午后 14:30-15:00 采集策略

**现象（2026-07-24 14:44 验证）**：
- `stock_zh_index_spot_em()` → 仅成功返回 上证/科创50（第1页），**深证/创业板缺失**（第2页或后续页失败）
- `stock_zh_a_spot_em()` → 3次重试全部 ConnectionError（58页爬取到第3-4页断连）
- `stock_board_industry_summary_ths()` → ConnectionError（同花顺接口也受影响，非东方财富独有问题）
- Tencent Finance API → 稳定（路径 D）

**建议步骤**：

```python
# Step 1: 先取 index spot（可能只返回第1页的指数）
indices = ak.stock_zh_index_spot_em()
# 只保证能取到: 上证指数(000001), 科创50(000688), 沪深300(000300)
# 可能缺失: 深证成指(399001), 创业板指(399006), 上证50(000016)

# Step 2: 缺失指数用 stock_zh_index_daily_em 补（sz 前缀）
if '399001' not in indices['代码'].values:
    df_sz = ak.stock_zh_index_daily_em(symbol="sz399001")
    last = df_sz.iloc[-1]
    prev = df_sz.iloc[-2]
    change_pct = (last['close'] - prev['close']) / prev['close'] * 100
    print(f"深证成指(日K补): {last['close']:.2f} ({change_pct:+.2f}%)")

# Step 3: 个股日K线稳定（非实时，不受限流）
indiv = ak.stock_zh_a_hist(symbol="000938", period="daily",
                           start_date="20260720", end_date="20260724", adjust="qfq")
```

### 个股行情采集（14:30 窗口也稳定）

```python
# stock_zh_a_hist() 在午后窗口仍然可靠（非实时，是日K线）
df = ak.stock_zh_a_hist(symbol="000938", period="daily",
                        start_date="20260720", end_date="20260724", adjust="qfq")
last = df.iloc[-1]
pre_close = df.iloc[-2]['收盘']
change_pct = (last['收盘'] - pre_close) / pre_close * 100
```

### ⚠️ 同花顺行业接口 `stock_board_industry_summary_ths()` — 午后可能同样不可用

- **早盘窗口** ✅：该接口极快（0-2s），是早盘首选的板块排名数据源（2026-07-20 验证）
- **午后窗口** ❌：2026-07-24 14:46 验证返回 `Connection aborted`。说明**同花顺接口在午后窗口也被限流**。
- **建议**：午后窗口优先用 Tencent Finance 路径获取板块排名；如 Tencent 也无法获取，退守指数+个股的 claims-only 分析。

## ❌ 不可用的函数

| 函数 | 问题 | 现象 |
|------|------|------|
| `stock_zh_a_spot_em()` | 超时 + 午后断连 | 58页爬取，每页~1s，午后第3-4页即断连 |
| `stock_board_industry_spot_em()` | 格式异常 | 被 AKShare 1.18.x 新版展示为 `['item','value']` 摘要，不包含每个行业数据 |
| `stock_board_concept_spot_em()` | 同上 | 同上 |
| `stock_board_industry_em()` | 不存在（akshare 1.18.64） | AttributeError: module 'akshare' has no attribute |
| `stock_board_concept_em()` | 不存在（akshare 1.18.64） | AttributeError: module 'akshare' has no attribute |
| `stock_board_concept_hist_em()` | ConnectionError（午后窗口） | RemoteDisconnected |
| `stock_board_industry_hist_em()` | ConnectionError（午后窗口） | RemoteDisconnected |
| `stock_hsgt_north_net_flow_in_em()` | 被移除 | ModuleNotFoundError |
| `stock_em_hsgt_north_flow()` | 不存在（akshare 1.18.64） | ModuleNotFoundError |
| `stock_hsgt_north_flow_em()` | 不存在 | ModuleNotFoundError |
| `stock_hsgt_north_flow()` | 不存在 | ModuleNotFoundError |

## 量能估算方法

### 当日半日 → 全天估算

```python
# Step 1: 取上证指数成交额
sh = indices[indices['代码'] == '000001'].iloc[0]
sh_vol = sh['成交额'] / 1e8  # 亿

# Step 2: 取深证成指成交额
sz = indices[indices['代码'] == '399001'].iloc[0]
sz_vol = sz['成交额'] / 1e8  # 亿

# Step 3: 合计 → 两市半日成交总额
total_half = sh_vol + sz_vol

# Step 4: 预估全天（系数1.7-1.9，半日约占全天的52-58%）
total_day_est = total_half / 0.55
```

如果没有399001数据（该指数可能不在EM的沪深范围），可以用沪深300成交额乘以一个系数来替代估算。

### 首小时量能同比法（2026-07-24 验证，用于 10:00 盘面确认）

**场景**：10:00 AM（开盘52分钟），需判断今日量能相对昨日是放量还是缩量。

**方法**：对比今日首小时成交量 vs 昨日全天成交量，用时间比例反推。

```python
import akshare as ak
from datetime import datetime

# Step 1: 取今日当前成交量（从 Tencent 或 EastMoney 实时行情）
# 上证指数实时量: ty_vol_lots ~219百万手 (219534988手)
today_lots = 219534988  # 示例：2026-07-24 10:22 数据

# Step 2: 取昨日全天成交量（从 AKShare 日K线）
hist = ak.stock_zh_index_daily(symbol="sh000001")
yest_row = hist.iloc[-2]  # -1=今日(未完整)，-2=昨日
yest_volume_shares = yest_row['volume']  # 单位: 股数
yest_lots = yest_volume_shares / 100      # 转换为手

# Step 3: 计算同比
ratio = today_lots / yest_lots * 100
print(f"今日10:22成交量: {today_lots/1e6:.1f}万手")
print(f"昨日全天成交量: {yest_lots/1e6:.1f}万手")
print(f"当前量 / 昨日全天: {ratio:.1f}%")

# Step 4: 判断
# 首小时(9:30-10:30)通常占全日 20-25%
# 当前时间占比: 52min / 240min ≈ 21.7%
if ratio > 28:
    print("=> 量能偏大（放量，有抛压或抄底资金）")
elif ratio > 22:
    print("=> 量能正常（与昨日节奏相当）")
elif ratio > 15:
    print("=> 量能偏小（缩量，观望情绪重）")
else:
    print("=> 量能显著萎缩（需警惕流动性问题）")
```

**判断基准**：
| 当前量/昨日全天 | 标尺（10:00-10:30） | 含义 |
|:---:|:---:|------|
| >28% | 放量 | 今日有增量资金入场或抛压加大，需结合涨跌幅判断方向 |
| 22-28% | 正常 | 与昨日节奏一致，无显著变化 |
| 15-22% | 缩量 | 观望情绪，可能继续阴跌或窄幅震荡 |
| <15% | 显著萎缩 | 流动性下降，警惕午后跳水或变盘 |

**注意事项**：
- 10:00-10:30 通常占全日交易时间约 20-22%（52-60分钟 / 240分钟）
- **不要直接用量比（量比=今日每分钟/过去5日平均每分钟成交量）替代**：量比是滚动5日日均，不能反映"首小时 vs 昨日全天"的绝对值变化
- 深证同理可做独立验证。上证+深证同步放量/缩量说明是全市场行为；分化则说明资金在交易所间轮动

```python
# Step 1: 取上证指数成交额
sh = indices[indices['代码'] == '000001'].iloc[0]
sh_vol = sh['成交额'] / 1e8  # 亿

# Step 2: 取深证成指成交额
sz = indices[indices['代码'] == '399001'].iloc[0]
sz_vol = sz['成交额'] / 1e8  # 亿

# Step 3: 合计 → 两市半日成交总额
total_half = sh_vol + sz_vol

# Step 4: 预估全天（系数1.7-1.9，半日约占全天的52-58%）
total_day_est = total_half / 0.55
```

如果没有399001数据（该指数可能不在EM的沪深范围），可以用沪深300成交额乘以一个系数来替代估算。

## 完整分析管线（已证实时序）

```
1. stock_zh_index_spot_em()      → 指数行情 + 量比         (~5s)
2. stock_board_industry_summary_ths() → 行业板块排名       (~2s)
3. stock_zh_index_daily()        → 历史K线对比              (~1s)
4. 整合分析：大小盘分化 + 板块结构 + 量能对比               (~0s)
总计: ~8-10秒 → 可产出完整上午盘面分析
```

**管线特点**：全部使用已验证的稳定AKShare接口，不依赖东方财富HTTP API直连，无需额外安装requests，在Hermes cron环境下可直接执行。
