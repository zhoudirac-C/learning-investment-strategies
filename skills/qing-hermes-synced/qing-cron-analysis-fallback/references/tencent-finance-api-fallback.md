# Tencent Finance API — 实时 A 股数据直连（轻型降级路径）

> 适用场景：AKShare 失效 + Eastmoney push2 API 被限流时，作为备用降级路径（路径 D）。
> 已验证：2026-07-21 10:00 盘面确认 cron job 中成功使用。

## 为什么需要这个

`qing-cron-analysis-fallback` 已有四级降级链（AKShare → Eastmoney HTTP → Sina → claims-only），但在以下情况需要额外备选：

1. **AKShare 安装/版本问题**（hu
ggingface-hub 冲突 / py_mini_racer 缺失）→ 路径 B 不可用
2. **Eastmoney push2 API 被限流**（返回 404 / `RemoteDisconnected`）→ 路径 A 不可用
3. **Sina API 不稳定**（频繁超时/空响应）→ 路径 C 不可用

Tencent Finance API（`qt.gtimg.cn` / `web.ifzq.gtimg.cn`）**不依赖任何第三方 Python 包**，仅需 `curl`，是环境最稳定的降级选项。

**GBK 解码注意**：该 API 返回 GBK 编码。`iconv -f gb2312 -t utf-8` **不可靠**，部分中文会变为乱码（如 `��证指��`）。推荐直接在 Python 中 `.decode("gbk", errors="ignore")` 做解码，跳过 iconv 步骤。管道模式示例：
```bash
curl -s "https://qt.gtimg.cn/q=..." | python3 -c "
import sys
raw = sys.stdin.buffer.read().decode('gbk', errors='ignore')
for line in raw.split(';'):
    ...
"
```

## 核心端点

### 端点1：实时行情（含指数 + 个股）

```
GET https://qt.gtimg.cn/q={codes}
```

**参数**：逗号分隔的代码列表，格式 `sh6xxxxx` 或 `sz0xxxxx` 或 `sz3xxxxx` 或 `sh688xxx`

**示例**（批量查询指数）：
```bash
curl -s "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000688,sh000300,sh000016"
```

**返回格式**：GBK 编码，每行一个 `v_代码="字段1~字段2~...~字段N";`

**关键字段索引**（按 `~` 分割后的 parts）：

| 索引 | 字段 | 说明 |
|------|------|------|
| parts[1] | 名称 | 如 "上证指数" |
| parts[3] | 当前价 | 浮点数 |
| parts[4] | 昨收 | 浮点数 |
| parts[5] | 开盘价 | 浮点数 |
| parts[32] | 涨跌幅(%) | **注意：可能是如 "-1.08" 表示 -1.08%** |
| parts[33] | 最高价 | 浮点数 |
| parts[34] | 最低价 | 浮点数 |
| parts[35] | 三合一串 `最新价/成交量(手)/成交额(元)` | 斜杠分隔，可用于交叉校验 |
| parts[36] | 成交量（手） | 整数 |
| parts[37] | 成交额（**万元**） | 整数，**不是元**！÷1e4 得亿元 |

> **⚠️ 坑1**：涨跌幅字段是 parts[32]（不是 parts[3]）。涨跌幅示例值如 "-1.08" 即 -1.08%。
> **⚠️ 坑2（2026-08-11 实测确认）**：parts[37] 单位是 **万元**，不是文档早期标注的"元"。验证方法：对比 parts[35] 内嵌的成交额(元) `692473596147` ≈ parts[37] `69247360` × 1e4（分毫不差）。换算亿元时用 `float(parts[37])/1e4`。

**Python 解析示例**：
```python
import subprocess, json, re

def fetch_tencent_quotes(codes: list[str]) -> list[dict]:
    """批量获取 Tencent 实时行情"""
    url = f"https://qt.gtimg.cn/q={','.join(codes)}"
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("gbk", errors="ignore")
    
    result = []
    for line in raw.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        parts = line.split("~")
        if len(parts) < 38:
            continue
        result.append({
            "name": parts[1],
            "code": parts[2],
            "price": float(parts[3]) if parts[3] else 0,
            "prev_close": float(parts[4]) if parts[4] else 0,
            "open": float(parts[5]) if parts[5] else 0,
            "high": float(parts[33]) if parts[33] else 0,
            "low": float(parts[34]) if parts[34] else 0,
            "change_pct": float(parts[32]) if parts[32] else 0,
            "volume": int(parts[36]) if parts[36] else 0,  # 手
            "amount_wan": int(parts[37]) if parts[37] else 0,  # 万元（÷1e4 得亿元）
        })
    return result
```

**常用代码**：

| 代码 | 名称 |
|------|------|
| `sh000001` | 上证指数 |
| `sz399001` | 深证成指 |
| `sz399006` | 创业板指 |
| `sh000688` | 科创50 |
| `sh000300` | 沪深300 |
| `sh000016` | 上证50 |
| `sz399005` | 中小100 |
| `sz399986` | 中证银行 |
| `sz399967` | 中证军工 |
| `sz399965` | 800地产 |
| `sz399966` | 800非银 |

### 端点2：日K线数据（**仅成交量，无成交额**）

```
GET https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq
```

**参数**：
- `code`：代码，格式 `sh000001` / `sz399001`
- `days`：最近 N 个交易日（建议 5-10）

**⚠️ 2026-08-11 实测**：每行固定 6 个字段，**不含成交额**（`len(row)==6`，字段[6] 不存在）：
`[日期, 开盘, 收盘, 最高, 最低, 成交量(手)]`
早期文档写"含成交额"是错的。需要成交额只能走端点1（实时）或东财 push2his（不稳定）。

**⚠️ 2026-08-26 实测修正**：实际每行 **7 个字段**（含成交额），字段[6] 存在。早期文档写"6 字段"是错的。正确结构：
`[日期, 开盘, 收盘, 最高, 最低, 成交量(手), 成交额(元)]`

**⚠️ JSON 响应结构（2026-08-26 实测）**：
```
{
  "code": 0,
  "msg": "",
  "data": {
    "sh000001": {
      "day": [[date, open, close, high, low, volume, amount], ...],
      "qt": {...},
      "mx_price": ...,
      "prec": ...,
      "version": ...
    }
  }
}
```
**正确解析路径**：`data["data"][code]["day"]`，不是 `data["day"]`。若 `data["data"][code]["day"]` 为空列表且 `code=0`，说明端点返回了空数据而非错误（如非交易日或代码格式错误）。

**用途**：比较今日半日成交量 vs 昨日全天成交量，推算量能变化。

### 量能预估：成交量比率法（无成交额时的替代，2026-08-11 验证）

当日K/实时接口拿不到昨日成交额时（东财 push2his 挂了、腾讯K线无 amount），用**成交量（手）比率**推算量能同比：

```python
# 腾讯K线昨日全天成交量 vs 腾讯实时今日半日成交量
# 上证示例：今日半日 340,337,215 手；昨日全天 542,118,110 手 → 半日已达昨日 62.8%
ratio = half_day_volume / yesterday_full_volume   # 62.8%
# 若下午与上午等量 → 全天 ≈ 昨日 × (62.8% × 2) ≈ 125.6%，即放量约 25%
```

**⚠️ 注意**：腾讯实时 parts[36] 才是成交量（手），parts[37] 是成交额（万元），两者别混。指数级别 `parts[36]` 对指数（如 sh000001）返回的是指数成交量口径，与个股不同——量能同比只看比率，绝对值口径不一致不影响趋势判断。

**⚠️ Sina 日K无成交额**：`quotes.sina.cn/cn/api/jsonp_v2.php/...CN_MarketDataService.getKLineData` 返回的 `amount` 字段对指数**恒为 0**（2026-08-11 实测），不能用于量能对比，放弃这条路径。

### 端点3：日内分时K线（30分钟 / 5分钟等）

```
GET https://web.ifzq.gtimg.cn/appstock/app/kline/mkline?param={code},{period},,,{count}
```

⚠️ **注意**：此端点已出现 301 重定向，部分时段不可用。优先使用端点2（日K线）。

## 与已知降级链的对比

| 维度 | 路径A (Eastmoney) | 路径B (AKShare) | 路径D (Tencent) |
|------|-------------------|-----------------|-----------------|
| 依赖 | requests | AKShare + pandas | 仅 urllib/curl |
| 实时行情 | ✅ | ✅ | ✅ |
| 日K线（成交量） | 需不同端点 | ✅ | ✅（端点2） |
| 板块排行 | ✅ | ⚠️ 部分失效 | ❌ 不支持 |
| 涨跌停家数 | ✅ | ✅ | ❌ 需多步推导 |
| 北向资金 | ❌ | ❌ | ❌ |
| 稳定性 | 偶发限流 | 依赖版本兼容 | **最稳定** |
| 速度 | 快 | 慢(~5-10s) | **极快(~0.5s)** |

**建议优先级**：
- 需要板块排行 / 涨跌停家数 → 路径A (Eastmoney) 首选
- 仅需指数行情 + 日K线量能对比 → **路径D (Tencent) 首选**（最快最稳）
- AKShare 可用且需要复杂数据 → 路径B

## 已验证的调用模式（2026-07-21 全盘面确认）

### 模式1：指数行情批量查询 + K线量能同比（上午/午后通用）

```bash
# Step 1: 批量获取主要指数行情（Python 解析，跳过 iconv）
curl -s "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000688,sh000300,sh000016" \
  | python3 -c "
import sys
raw = sys.stdin.buffer.read().decode('gbk', errors='ignore')
for line in raw.strip().split(';'):
    parts = line.split('~')
    if len(parts) < 38: continue
    name = parts[1]; price = parts[3]; pct = parts[32]
    high = parts[33]; low = parts[34]; vol = float(parts[37])/1e8 if parts[37] else 0
    print(f'{name}: {price}  {pct}%  高{high}  低{low}  成交{vol:.0f}亿手')
"

# Step 2: 获取最近 5 个交易日 K 线（用于量能同比）
curl -s "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,,,5,qfq" \
  | python3 -c "import sys,json; d=json.loads(sys.stdin.read())
for k in d['data']['sh000001']['day']:
    print(f'{k[0]}: 收{float(k[2]):.2f}  量{float(k[5])/1e8:.2f}亿手')"
```

### 模式2：监控标的批量行情查询（watchlist 场景，2026-07-21 下午确认）

适合从 `config/stock_monitor/watchlist.yaml` 中提取代码后的批量查询。单次请求即可返回所有标的：

```bash
# 查询8只监控标的
curl -s "https://qt.gtimg.cn/q=sz002409,sz001258,sz002432,sh603118,sh603698,sz002208,sz001309,sz002281" \
  | python3 -c "
import sys
raw = sys.stdin.buffer.read().decode('gbk', errors='ignore')
for line in raw.strip().split(';'):
    parts = line.split('~')
    if len(parts) < 38: continue
    name = parts[1]; code = parts[2]
    price = parts[3]; pct = parts[32]
    open_p = parts[5]; high = parts[33]; low = parts[34]
    print(f'{name}({code}): {price}  {pct}%  开{open_p}  高{high}  低{low}')
"
```

**返回示例**（2026-07-21 13:16 实际数据）：
```
雅克科技(002409): 140.88  7.95%  开132.00  高142.77  低117.45
立新能源(001258): 10.01  10.00%  开10.01  高10.01  低9.55
九安医疗(002432): 79.75  10.00%  开75.05  高79.75  低73.27
共进股份(603118): 14.93  10.02%  开13.13  高14.93  低12.73
```

**代码格式规则**：
- 上交所（6开头/688开头）：`sh` + 代码
- 深交所（0开头/3开头/001开头）：`sz` + 代码

## 已知限制

| 能力 | 状态 | 替代方案 |
|------|------|---------|
| 指数实时行情 | ✅ | — |
| 个股实时行情 | ✅ | — |
| **ETF 实时行情** | ✅ **（唯一可用源）** | Eastmoney push2 对 ETF secid 统一返回 `rc=102`，ETF **必须**走 Tencent `qt.gtimg.cn` |
| 日K线 + 成交量 | ✅ | — |
| 板块排行 | ❌ | 必须走 Eastmoney 路径A |
| 北向资金 | ❌ | 数据源本身不提供 |
| 涨跌停家数 | ❌ | 需走 Eastmoney 全市场模式推导 |
| 分时K线（5/30min） | ⚠️ 301重定向 | 日K线端点稳定可用 |

## ⚠️ ETF 代码格式（2026-08-27 实测）

ETF 与指数/个股代码格式一致：上交所 5 开头用 `sh` 前缀（如 `sh588170` 科创半导体ETF华夏），深交所 1 开头用 `sz` 前缀（如 `sz159516` 半导体设备ETF国泰）。

## ⚠️ 批量大小限制（2026-08-27 实测）

单次 `?q=` 参数超过 ~15 个代码时 `curl` 返回 HTTP 52 空 body（即使加 UA/Referer 头）。**必须分块**：每次 6-9 个代码，组间 `sleep 1-2s`。

## ⚠️ `execute_code()` 内嵌 GBK 管道陷阱（2026-08-27 实测）

Tencent 返回 GBK，decode 后含控制字符 → `execute_code()` 的 terminal 包装器 JSON.parse 抛 `Invalid control character`。**正确姿势**：`write_file` 落独立 py 脚本（`urllib.request + decode('gbk', errors='ignore')`）再 `python3 file.py` 运行，禁止在 `execute_code()` 中内联 `curl | python3 -c` 管道。

## ⚠️ Eastmoney push2 对 ETF 的固定失败（2026-08-27 实测）

Eastmoney `push2.eastmoney.com/api/qt/ulist.np/get?secids=1.588170`（或 `2.588170`）对 ETF 统一返回 `{"rc":102,"data":null}`，与限流/网络无关——**ETF 行情只能走 Tencent `qt.gtimg.cn`，不要尝试 push2 重试**。

## 参考

- `qing-agent-cli` skill 的 `references/chat-realtime-data-fetching.md` 也使用了相同的 Tencent API，但集成在 `/chat` 端点中（间接调用）
- `references/intraday-volume-ratio-technique.md` — 日内量能比率分析完整流程（Tencent 实时量 vs K线昨日量），含 2026-08-26 验证数据
- 本参考文件是**独立直连方案**，不经过 Qing-Agent 服务，直接由 Hermes cron job 使用

## 更新记录

- **2026-08-26**：修正日K线端点字段数（6→7，含成交额）、修正 JSON 响应结构路径（`data["data"][code]["day"]`）、修正 `amount` 字段注释（万元非元）。详见 session-20260826-1450 案例。
