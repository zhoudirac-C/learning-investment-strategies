# TDX 实时行情直连（路径 E 延伸 — 2026-07-30 验证）

## 概述

`qing_investment.tdx_market.TdxMarket` 不仅支持 K 线降级（路径 E），也可直接获取**实时个股/指数行情**（price / pct_change / open / high / low / volume / amount），且响应极快（~50ms）。在 HTTP API 全部失败时，TDX 直连作为零 HTTP 依赖的终端方案，可靠性最高。

2026-07-30 09:51 实测：主脚本超时 + 东方财富 HTTP API 无响应的情况下，TDX `get_quote()` 成功返回全部主要指数和监控标的实时数据。

## 导入与初始化

```python
import sys
sys.path.insert(0, "/home/ubuntu/learning-investment-strategies/src")
from qing_investment.tdx_market import TdxMarket

mkt = TdxMarket()
# 无需额外配置，默认连接通达信行情服务器
```

> **注意**：使用 `.venv/bin/python` 确保 `qing_investment` 包可访问。导入路径为 `qing_investment.tdx_market`（非 `qing_investment.tdx_market.market`）。

## 指数实时行情

```python
indices = {
    "上证指数": "999999",
    "深证成指": "399001",
    "创业板指": "399006",
    "科创50": "000688"
}

for name, code in indices.items():
    q = mkt.get_quote(code)
    if q and q.get("price"):
        pc = q.get("pct_change", 0) or 0
        print(f'{name}({code}): 开={q.get("open","N/A")} '
              f'现={q.get("price","N/A")} {pc:+.2f}% '
              f'高={q.get("high","N/A")} 低={q.get("low","N/A")} '
              f'昨收={q.get("prev_close","N/A")}')
```

**返回字段**: code, name, price, prev_close, open, high, low, volume, amount, cur_vol, buy_vol, sell_vol, change, pct_change, is_index, bid, ask, source

## 个股实时行情

```python
# ✅ 个股用 get_quote(code) — 逐个获取，单次 ~50ms
stock = mkt.get_quote("600519")
if stock and stock.get("price"):
    print(f'{stock.get("name")}: {stock.get("price")} '
          f'{stock.get("pct_change",0):+.2f}% '
          f'量={stock.get("volume",0)}')

# ❌ 注意：get_quotes([codes]) 批量接口在2026-07-30返回为空
# 不要依赖批量接口，逐个调用 get_quote()
codes = ["002185", "000938", "603986"]
for code in codes:
    q = mkt.get_quote(code)
    if q and q.get("price"):
        print(f'{q.get("code")}: {q.get("price")} {q.get("pct_change",0):+.2f}%')
```

## 历史 K 线对比

指数 K 线和个股 K 线均可用：

```python
# 指数日K线
sh_kl = mkt.get_index_kline("999999", count=5)  # 近5天
for k in sh_kl:
    print(f'{k["date"]} O={k["open"]} C={k["close"]} '
          f'H={k["high"]} L={k["low"]} V={k["volume"]/1e6:.0f}万')

# 个股日K线
kl = mkt.get_kline("600519", count=5)
```

## 数据坑位

### 坑1：get_quotes() 批量接口可能返回空

2026-07-30 09:51 实测 `mkt.get_quotes(codes)` 传入多个股票代码后返回空列表（每个元素为 None），而逐个调用 `get_quote()` 正常返回。**始终用单体 `get_quote()` 替代批量 `get_quotes()`**。

### 坑2：指数 volume 是手数，amount 是成交额

- `volume`: 成交手数（用于同比昨日）  
- `amount`: 成交额（元），需 `/ 1e8` 转为亿元

### 坑3：get_kline() 返回不含 name

个股 K 线返回的 dict 没有 `name` 字段。如需名称，用 `get_quote()` 的 `name` 字段获取。

### 坑4：每日首次调用可能稍慢

首次 `TdxMarket()` 初始化会连接行情服务器，约 200-500ms。后续所有 `get_quote()` 调用约 50ms 以内。

### 坑5：科创50 裸代码 `get_quote("000688")` 会 mis-resolve（2026-08-04 实测）

直接 `mkt.get_quote("000688")` 或 `mkt.get_index_kline("000688")` 返回**错误标度**数据（价格 ~29、成交额 4.7亿 —— 真实科创50 约 1612 点、成交额千亿级）。涨幅方向可参考但数值不可信，**不要写进报告**。

**正确做法**：用项目 fetcher 带市场前缀解析（内部走 resolve_symbol）：

```python
from qing_investment.monitor.fetchers import fetch_quotes_with_fallback
quotes = fetch_quotes_with_fallback({'科创50': '1.000688'})  # 返回 1612.58 (+3.84%)，与 scanner 一致
```

**通用交叉验证规则**：TDX 返回明显不合常理（价格标度/成交额量级不对）时，先与 `config/stock_monitor/daily_state.json` 的 `market_stage.detail`（含各指数涨幅，scanner 已算好）比对，确认后再用。指数间细微差异（如 +3.84% vs +4.05%）多为采样时点差，报告中声明时间戳即可。

## 实用分析模板（开盘15分钟确认）

```python
def opening_check(mkt):
    """返回开盘15分钟确认所需的核心数据"""
    # 1. 主要指数
    # ⚠️ 科创50 不要用裸代码 "000688"（会 mis-resolve，见坑5），用 fetcher 带市场前缀或从 daily_state 取
    indices_data = {}
    for name, code in {
        "上证指数": "999999", "深证成指": "399001",
        "创业板指": "399006", "科创50": "000688"  # 仅上证/深证/创业板可直接 get_quote
    }.items():
        q = mkt.get_quote(code)
        if q and q.get("price"):
            indices_data[name] = q
    
    # 2. 监控标的
    stocks_data = {}
    for code in ["002185", "000938", "603986", "600118", "600343"]:
        q = mkt.get_quote(code)
        if q and q.get("price"):
            stocks_data[q.get("code","")] = q
    
    # 3. 量能估算（上证+深证）
    sh = indices_data.get("上证指数", {})
    sz = mkt.get_quote("399001") or {}
    sh_amount = sh.get("amount", 0) / 1e8 if sh.get("amount") else 0
    sz_amount = sz.get("amount", 0) / 1e8 if sz.get("amount") else 0
    total_15min = sh_amount + sz_amount  # 前15分钟成交额合计(亿)
    
    # 4. 历史参照（昨日量能基准）
    yesterday = mkt.get_index_kline("999999", count=2)[-1]  # 昨天
    yesterday_vol = yesterday.get("volume", 0)  # 手数
    
    return {
        "indices": indices_data,
        "stocks": stocks_data,
        "total_15min_amount": total_15min,
        "yesterday_volume": yesterday_vol
    }
```

## 与其他路径的定位关系

| 路径 | 数据完整性 | 速度 | HTTP 依赖 | 使用时序 |
|------|-----------|------|----------|---------|
| B (AKShare) | 高（指数+板块+全A+历史） | 慢（8-10s） | 是 | 首选 |
| A (EastMoney HTTP) | 中高（指数+板块排行+KDJ） | 中（1-2s） | 是 | 次选 |
| D (Tencent Finance) | 中（指数+个股+K线量能） | 快（~0.5s） | 是 | 第三 |
| C (Sina API) | 中（指数+个股昨收可算涨幅） | 快（~0.5s） | 是 | 第四 |
| **E (TDX TdxMarket)** | 中高（指数+个股+K线1/5分日） | 最快（~50ms） | **否** | **终末保底** |

TDX 路径的核心优势：**零 HTTP 依赖**。当东方财富限流/AKShare 崩溃/Sina 被封/Tencent 无响应时，TDX 直连通达信行情端口仍是备用的可靠方案。
