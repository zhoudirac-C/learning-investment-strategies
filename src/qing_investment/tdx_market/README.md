# qing_investment.tdx_market 接口参考

基于通达信 TDX 协议的 A 股行情数据接口（pytdx 封装）。直连通达信官方行情服务器。

## 初始化

```python
from qing_investment.tdx_market import TdxMarket

mkt = TdxMarket()
```

可选自定义客户端参数（见末尾 `TdxClient`）：

```python
from qing_investment.tdx_market import TdxMarket, TdxClient
mkt = TdxMarket(client=TdxClient(max_attempts=10, connect_timeout=20))
```

## 股票代码格式

`get_quote` / `get_kline` 等接口的 `code` 参数支持以下写法（自动识别市场）：

| 写法 | 市场 |
|------|------|
| `"600519"` / `"sh600519"` / `"600519.sh"` / `"600519.ss"` | 沪市 |
| `"000001"` / `"sz000001"` / `"000001.sz"` | 深市 |
| `"830xxx"` / `"430xxx"` / `"920xxx"` | 北交所 |
| `"999999"` | 上证指数 |
| `"399001"` / `"399006"` | 深证成指 / 创业板指 |
| `"880xxx"` | 通达信行业板块指数 |

## 接口

---

### get_quote(code)

获取单只股票/指数的实时行情。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `code` | str | — | 股票或指数代码 |

**返回** `dict | None`，字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | str | 6 位代码 |
| `name` | str \| None | 证券名称（pytdx 不返回，通常为 None） |
| `price` | float \| None | 最新价 |
| `prev_close` | float \| None | 昨收 |
| `open` / `high` / `low` | float \| None | 开/高/低 |
| `volume` | float \| None | 成交量 |
| `amount` | float \| None | 成交额 |
| `cur_vol` | float \| None | 当前成交量 |
| `buy_vol` / `sell_vol` | float \| None | 买盘/卖盘累计成交量 |
| `change` | float \| None | 涨跌额 |
| `pct_change` | float \| None | 涨跌幅(%) |
| `is_index` | bool | 是否指数 |
| `bid` | list | 五档买盘，5 个 `{price, volume}` |
| `ask` | list | 五档卖盘，5 个 `{price, volume}` |
| `source` | str | 固定 `'tdx'` |

```python
q = mkt.get_quote("600519")
# {'code':'600519','price':1316.68,'prev_close':1253.0,'pct_change':5.08,
#  'bid':[{'price':1315.53,'volume':3},...],'ask':[{'price':1316.71,'volume':1},...],...}
```

---

### get_quotes(codes)

批量获取实时行情，自动按 80 支分批请求。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `codes` | list[str] | — | 股票/指数代码列表 |

**返回** `list[dict]`，元素字段同 `get_quote`。

```python
qs = mkt.get_quotes(["600519", "000001", "300750"])
```

---

### get_kline(code, category, count, start)

获取个股或指数 K线。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `code` | str | — | 股票或指数代码 |
| `category` | str \| int | `"daily"` | K线周期，见下表 |
| `count` | int | 100 | K线数量，单次 ≤800 |
| `start` | int | 0 | 起始位置，0=最新一根 |

`category` 取值：

| 字符串 | 数字 | 含义 | 字符串 | 数字 | 含义 |
|--------|------|------|--------|------|------|
| `"5min"` | 0 | 5 分钟 | `"monthly"` / `"month"` | 6 | 月K |
| `"15min"` | 1 | 15 分钟 | `"1min"` | 7 | 1 分钟 |
| `"30min"` | 2 | 30 分钟 | `"quarter"` | 10 | 季K |
| `"60min"` / `"1hour"` | 3 | 60 分钟 | `"year"` | 11 | 年K |
| `"daily"` / `"day"` | 4 | 日K | | | |
| `"weekly"` / `"week"` | 5 | 周K | | | |

**返回** `list[dict]`，按时间正序，字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | str | 日期，`YYYY-MM-DD` |
| `datetime` | str \| None | 完整时间戳（分钟K线带时分） |
| `open` / `close` / `high` / `low` | float \| None | OHLC |
| `volume` | float \| None | 成交量 |
| `amount` | float \| None | 成交额 |
| `pct_change` | float \| None | 涨跌幅(%)，基于前一根 close 计算 |
| `source` | str | `'tdx'` |

```python
kl = mkt.get_kline("600519", category="daily", count=10)
# [{'date':'2026-07-20','open':1270.0,'close':1320.62,'high':1326.0,...},...]
mkt.get_kline("600519", category="30min", count=50)   # 30分钟K
```

---

### get_index_kline(code, category, count, start)

获取指数 K线。参数与返回同 `get_kline`，对指数代码调用走 `get_index_bars`。

```python
ik = mkt.get_index_kline("999999", count=5)   # 上证指数近5日
```

---

### get_intraday(code)

获取当日分时数据。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `code` | str | — | 股票代码 |

**返回** `list[dict]`，字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `price` | float \| None | 分时价格（pytdx 返回归一化值，非真实价） |
| `volume` | float \| None | 该分钟成交量 |
| `source` | str | `'tdx'` |

```python
intraday = mkt.get_intraday("600519")
```

---

### get_history_intraday(code, date)

获取历史分时数据。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `code` | str | — | 股票代码 |
| `date` | str | — | 日期，格式 `YYYYMMDD` |

**返回** `list[dict]`，字段 `price` / `source`。

```python
hd = mkt.get_history_intraday("600519", "20260718")
```

---

### get_transaction(code, start, count)

获取当日分笔成交。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `code` | str | — | 股票代码 |
| `start` | int | 0 | 起始位置 |
| `count` | int | 2000 | 数量，单次 ≤2000 |

**返回** `list[dict]`，字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `time` | str \| None | 成交时间 |
| `price` | float \| None | 成交价 |
| `volume` | float \| None | 成交量 |
| `buyorsell` | int \| None | 0=中性，1=买盘，2=卖盘 |
| `source` | str | `'tdx'` |

```python
tx = mkt.get_transaction("600519", count=100)
```

---

### get_finance(code)

获取财务信息（最新一期）。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `code` | str | — | 股票代码 |

**返回** `dict`，含 pytdx 原始财务字段 + `source='tdx'`。

```python
fin = mkt.get_finance("600519")
```

---

### get_xdxr(code)

获取除权除息信息。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `code` | str | — | 股票代码 |

**返回** `list[dict]`，每条字段：

| 字段 | 说明 |
|------|------|
| `year` / `month` / `day` | 除权日期 |
| `category` | 类别 |
| `fenhong` | 分红 |
| `peigujia` | 配股价 |
| `songzhuangu` | 送转股 |
| `peigu` / `suogu` | 配股 / 缩股 |
| `panqianliutong` / `panhouliutong` | 盘前/盘后流通 |
| `qianzongguben` / `houzongguben` | 前/后总股本 |
| `fenshu` / `xingquanjia` | 分数 / 行权价 |
| `source` | `'tdx'` |

```python
xdxr = mkt.get_xdxr("600519")   # 茅台实测 45 条
```

---

### get_security_list(market, start, count)

获取证券列表（分页）。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `market` | int | — | 市场：0=深, 1=沪 |
| `start` | int | 0 | 起始位置 |
| `count` | int | 1000 | 数量（pytdx 内部固定每页 1000，count 仅文档用） |

**返回** `list[dict]`，每条含 `code` / `longname` / `shortname` 等 + `source='tdx'`。

注意：当前服务器环境该方法可能返回空（pytdx 已知问题）。

```python
sl = mkt.get_security_list(1, 0)   # 沪市第一页
```

---

### get_block_info(blockfile)

解析板块文件。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `blockfile` | str | `"block_zs.dat"` | 板块文件名 |

常用 `blockfile`：

| 文件 | 含义 |
|------|------|
| `block_zs.dat` | 指数板块 |
| `block_gn.dat` | 概念板块 |
| `block_fg.dat` | 风格板块 |

**返回** `list[dict]`，每条含板块名、成分股代码列表 + `source='tdx'`。

```python
blocks = mkt.get_block_info("block_gn.dat")   # 概念板块
```

---

## 工具函数

### resolve_symbol(code)

解析股票代码为市场编号与纯代码。

| 参数 | 类型 | 说明 |
|------|------|------|
| `code` | str | 股票/指数代码 |

**返回** `tuple[int, str, bool]`：

| 位置 | 说明 |
|------|------|
| 0 | market：0=深, 1=沪 |
| 1 | pure_code：6 位纯数字代码 |
| 2 | is_index：是否指数 |

```python
from qing_investment.tdx_market import resolve_symbol
resolve_symbol("600519")        # (1, '600519', False)
resolve_symbol("000001")        # (0, '000001', False)
resolve_symbol("999999")        # (1, '999999', True)
resolve_symbol("399001")        # (0, '399001', True)
```

---

## 底层客户端 TdxClient

`TdxMarket` 基于 `TdxClient`。如需调用 pytdx 原生方法，可直接用 `execute`：

```python
from qing_investment.tdx_market import TdxClient, Cap

client = TdxClient()
# execute(能力, op, retry_empty=False)
# op 接收一个已连接的 pytdx API 实例，返回其调用结果
result = client.execute(
    Cap.CapMainQuote,
    lambda api: api.get_security_quotes([(1, '600519')]),
    retry_empty=True,
)
```

### TdxClient 构造参数

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `connect_timeout` | float | 15.0 | 连接超时（秒） |
| `fail_threshold` | int | 3 | 连续失败多少次后熔断该服务器 |
| `cooldown` | float | 60.0 | 熔断时长（秒） |
| `max_attempts` | int | 5 | 一次 `execute` 最多尝试多少台服务器 |
| `heartbeat` | bool | True | 心跳保活 |
| `auto_retry` | bool | True | pytdx 单连接内自动重试 |
| `rng` | Random \| None | None | 加权随机数生成器（测试用） |

### execute 参数

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `cap` | HostCapability | — | 能力枚举，决定路由到哪类服务器 |
| `op` | callable | — | `op(api, *args, **kwargs)`，`api` 为已连接的 pytdx API |
| `*args` | — | — | 透传给 `op` |
| `retry_empty` | bool | False | True 时返回空（None/空 list）视为软失败，切换下一台 |
| `**kwargs` | — | — | 透传给 `op` |

### 能力枚举 Cap（HostCapability）

| 枚举 | 用途 |
|------|------|
| `Cap.CapMainQuote` | A 股实时行情 |
| `Cap.CapMainKline` | A 股/指数 K线 |
| `Cap.CapMainList` | 证券列表 |
| `Cap.CapMainMinute` | 分时数据 |
| `Cap.CapMainTrade` | 分笔成交 |
| `Cap.CapMainFinance` | 财务数据 |
| `Cap.CapMainXdxr` | 除权除息 |
| `Cap.CapSector880` | 板块数据 |
| `Cap.CapExQuote` | 港股行情（Ex 协议，当前不可用） |
| `Cap.CapExKline` | 港股 K线（Ex 协议，当前不可用） |

---

## 异常

| 异常 | 说明 |
|------|------|
| `TdxError` | 所有异常基类 |
| `TdxConnectionError` | 所有候选服务器均连接失败 |
| `TdxDataError` | 服务器已连接但返回数据异常 |
| `TdxSymbolError` | 股票代码无法识别 |

```python
from qing_investment.tdx_market import TdxConnectionError, TdxSymbolError
try:
    mkt.get_quote("600519")
except TdxConnectionError as e:
    print("所有服务器不可用:", e)
except TdxSymbolError as e:
    print("代码错误:", e)
```

---

## 已知限制

- 实时行情 `name=None`：pytdx 不返回证券名称
- 分时 `price` 为归一化值，非真实成交价
- 证券列表可能返回空（pytdx 已知问题）
- 外盘（港股/美股/日韩）不支持，用 akshare

## 自测

```bash
python scripts/tdx_market_selftest.py
```
