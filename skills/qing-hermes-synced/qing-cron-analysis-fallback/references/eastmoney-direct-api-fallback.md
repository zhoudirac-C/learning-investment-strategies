# 东方财富 HTTP API 直连 — 实时 A 股数据降级方案

> 适用场景：`qing_stock_monitor_agent.py` 脚本超时，但底层东方财富数据源仍可达。\n> 已验证：2026-07-20 10:27 成功使用。\n> 最后更新：2026-07-24 — 新增 `cb` 回调参数要求 + JSONP 解析 + per-minute 限流模式\n> **2026-08-11 行为回归**：`clist/get` 不带 `cb` 已可直接返回纯 JSON（不再强制 JSONP）；11:20-11:30 出现 `Remote end closed connection without response` 间歇失败，**加 `Referer: https://quote.eastmoney.com/` + 重试 2-3 次可恢复**；`push2his` 日K端点连续失败不可靠，昨日量能基数改用 Tencent 成交量比率法。详见文末「行为回归」节。\n\n## ⚠️ 重要：API 行为变更（2026-07-24）\n\n2026-07-24 观测到以下行为变更：\n\n1. **`cb` 回调参数强制要求**：不带 `cb=` 参数的请求返回空字符串（curl exit code 52）。必须在所有 `clist/get` 和 `ulist.np/get` 请求中附加 `cb=JQ`（任意回调名均可）。\n2. **JSONP 响应**：返回格式为 `JQ({...});`，不能直接 JSON 解析，需剥离回调 wrapper 后再解析。\n3. **Per-minute 限流**：`clist/get` 的行业板块（`m:90+t:2`）和概念板块（`m:90+t:3`）端点共享同一个限流桶——每次成功调用后约 30 秒内同一组端点返回空。`ulist.np/get`（指数/个股报价）限流桶更宽松。\n4. **Python `requests` 沙箱连接池耗尽**：execute_code 沙箱中的 `requests` 库连续调用 1-2 次后出现 `Connection aborted`。改用 `subprocess.run` + `curl` 从终端调用更可靠。

## 核心端点

```
GET https://push2.eastmoney.com/api/qt/clist/get
```

**⚠️ 2026-07-24 新发现：端点要求 cb 回调参数**。无 `cb=` 参数时返回空字符串（curl exit code 52），有 `cb=JQ` 则正常返回。所有请求必须附带回调参数。

**状态验证**（快速检查，带 cb 参数）：
```bash
RESP=$(curl -s --max-time 6 \
  "https://push2.eastmoney.com/api/qt/clist/get?cb=JQ&pn=1&pz=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:1+t:2+f:!2&fields=f2,f14")
# 验证是否有 JSONP wrapper
if echo "$RESP" | grep -q '^JQ('; then echo 'API_OK'; else echo 'API_FAILED'; fi
```

**响应解析**：JSONP 格式 `JQ({...});`，需剥离外层回调后再解析。
```python
import json
# 取括号内 JSON
start = text.index('(') + 1
end = text.rindex(')')
data = json.loads(text[start:end])
```

## 通用参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `pn` | 1 | 页码 |
| `pz` | 5000（全量） | 每页数量 |
| `po` | 1 | 排序方向（1=降序） |
| `np` | 1 | 是否分页 |
| `ut` | `bd1d9ddb04089700cf9c27f6f7426281` | 固定 token |
| `fltt` | 2 | 价格保留位数 |
| `invt` | 2 | 涨跌幅保留位数 |
| `fid` | `f3` | 排序字段（f3=涨跌幅排序） |
| `fs` | *见下方* | 筛选条件（核心参数） |
| `fields` | *见下方* | 返回字段 |
| `_` | 时间戳 | 缓存控制 |

> `ut` token 是固定的东方财富公网 token，硬编码即可。

## 按数据类型

### 1. 主要指数

```python
params = {
    "fs": "m:1+t:2+f:!2",  # 上证/深证/创业板/科创50等
    "fields": "f2,f3,f4,f12,f14,f20,f184",
}
```

**响应示例**（2026-07-20 10:27）：
```
上证指数: 3797.47 (+0.86%) 成交5667亿
科创50: 1701.14 (-0.92%) 成交80亿
沪深300: 4580.53 (+1.14%) 成交4164亿
```

### 1b. 轻量级涨跌家数比（ulist.np/get + f104/f105，2026-07-24 验证）

**场景**：10:00 盘面确认中需要快速确认涨跌家数比，但全市场 A 股扫描（>5000只）耗时 >30s，不可接受。

**方案**：用 `ulist.np/get` 查询单只指数行情（如 `1.000001` = 上证指数），其 `f104`/`f105` 字段直接返回该交易所实时上涨/下跌家数。

```bash
# 轻量级涨跌家数比 — 单请求，~0.5s
curl -s --connect-timeout 5 --max-time 10 \
  "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f4,f5,f6,f104,f105&secids=1.000001"
```

**返回示例**（2026-07-24 10:22 实测）：
```json
{"data":{"diff":[{
  "f2": 3842.12,    // 最新价
  "f3": -0.89,      // 涨跌幅(%)
  "f4": -34.66,     // 涨跌额
  "f5": 219534988,  // 成交量(手)
  "f6": 384381217257.6,  // 成交额(元)
  "f104": 355,      // ↑ 上涨家数
  "f105": 1965      // ↓ 下跌家数
}]}}
```

**Python 解析**：
```python
import subprocess, json
def get_up_down_ratio():
    result = subprocess.run([
        "curl", "-s", "--connect-timeout", "5", "--max-time", "10",
        "https://push2.eastmoney.com/api/qt/ulist.np/get",
        "--data-urlencode", "fltt=2",
        "--data-urlencode", "fields=f2,f3,f4,f5,f6,f104,f105",
        "--data-urlencode", "secids=1.000001",
    ], capture_output=True, text=True)
    d = json.loads(result.stdout)
    item = d["data"]["diff"][0]
    up, down = item["f104"], item["f105"]
    ratio = up / down if down > 0 else 0
    print(f"上证 上涨={up} 下跌={down} 涨跌比={ratio:.2f} (仅15%股票上涨)")
    return up, down, ratio
```

**注意事项**：
- 此端点 `ulist.np/get` 的限流桶比 `clist/get` 宽松，连续调用 5-10 次无压力
- **⚠️ 2026-08-03 实测修正：push2 整体限流时此端点同样失效**——当 clist 概念板块也返回空响应（curl 成功但 body 为空，exit 0）时，`ulist.np/get` 即使带 `cb=JQ` + `_` 时间戳也会连续空响应 3 次以上。"限流桶宽松"只在 push2 未被整体限流时成立。**判定方法**：单请求返回空且 `echo "$RESP" | grep -q 'JQ('` 为假 → 直接放弃 EM 全家族（ulist + clist），转 THS/Sina/Tencent，不要逐个端点重试浪费 10:00 窗口
- **涨跌家数缺失时的替代源**：本地 `config/stock_monitor/daily_state.json` 的 `intraday_narrative`（scanner 每 ~10min 写入，含涨/跌家数与跌停数，2026-08-03 10:18 验证，延迟约 10-20min）；或 AKShare `stock_board_industry_summary_ths()` 各板块上涨/下跌家数求和
- 仅返回**上交所**（沪市）的涨跌家数，不含深市。如需全市场，可同时查 `0.399001`（深证成指）→ `f104`/`f105` 对应深市涨跌家数
- 与 §4（全市场 A 股扫描）对比：前者 ~0.5s，后者 ~30s+。**10:00 时间紧张的宏观分析场景优先用轻量级方案**
- 此端点也支持 `fields=f100`（停牌家数）等额外统计字段

### 2. 行业板块（56 个细分行业）

```python
params = {
    "fs": "m:90+t:2+f:!50",
    "fields": "f2,f3,f4,f6,f12,f14,f20,f104,f105",
}
```

**f6 — 成交额**（单位：元，手动除 1e8 得亿）。

**最新已验证的字段**（2026-07-20）：
| 字段 | 含义 | 类型 |
|------|------|------|
| f2 | 最新价 | float |
| f3 | 涨跌幅(%) | float |
| f4 | 涨跌额 | float |
| f6 | 成交额(元) | float |
| f12 | 板块代码 | str |
| f14 | 板块名称 | str |
| f20 | 总市值 | float |
| f104 | 上涨家数 | int |
| f105 | 下跌家数 | int |

### 3. 概念板块（200+）

```python
params = {
    "fs": "m:90+t:3+f:!50",
    "fields": "f2,f3,f4,f12,f14,f6",
}
```

### 4. 全市场 A 股（含北交所）

```python
params = {
    "fs": "m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2",
    "fields": "f2,f3,f4,f12,f14",
}
```

**可用推断**：
- 涨停家数：`sum(1 for s in stocks if s['f3'] >= 9.8)`
- 跌停家数：`sum(1 for s in stocks if s['f3'] <= -9.8)`
- 涨跌比：上涨/下跌

> ⚠️ **注意**：`f20`（成交额）在全市场模式下似乎返回异常数据。量能估算以指数级别的 `f20` 为准（见第1类），不要汇总个股 `f20`。

### 5. 主要 ETF

```python
params = {
    "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024",
    "fields": "f2,f3,f12,f14,f20",
    "fid": "f20",  # 按成交额排序
}
```

**产出价值**：ETF 成交额排名反映资金的主要流向。例如沪深300 ETF 成交第一（1007亿）暗示权重托底，科创芯片 ETF 资金流出则暗示科技减仓。

## 北向资金（盘中无法获取）

东方财富 HTTP API **不提供盘中北向数据**。盘中引用必须标注"北向实时数据暂不可用(盘中通常延迟)"。

如需盘后验证趋势，可用新浪/凤凰网接口（但盘中不可靠）。

### 已排查的北向资金端点（2026-07-21）

以下端点均经验证失败，不再重试：

| 端点 | 返回 | 结论 |
|------|------|------|
| `push2.eastmoney.com/api/qt/stock.get?secid=1.807060` | HTTP 404 | 此 secid 无效 |
| `datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_HSGT_MONEY_FLOW` | `{"success":false,"message":"报表配置不存在","code":9501}` | API 已变更 |
| `push2.eastmoney.com/api/qt/kamt.kline/get?secid=1.000001` | 返回空值（`0.00`） | 数据字段含义不明 |

**建议**：如急需北向数据，尝试使用 akshare 的 `stock_hsgt_north_net_flow_in_em()`（如可用）或 `stock_hsgt_north_net_flow_in_sina()`（如未废弃）。

## 完整 Python 示例

```python
import requests
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}
BASE_URL = "https://push2.eastmoney.com/api/qt/clist/get"

def fetch_em(fs, fields="f2,f3,f4,f12,f14,f20"):
    params = {
        "pn": 1, "pz": 5000, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": fs, "fields": fields,
        "_": "1623888000000",
    }
    resp = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
    return resp.json().get("data", {}).get("diff", [])

# 获取行业板块涨跌幅
sectors = fetch_em("m:90+t:2+f:!50", "f2,f3,f4,f12,f14,f6")
sectors.sort(key=lambda x: x.get("f3", 0), reverse=True)
print("涨幅 TOP 5:")
for s in sectors[:5]:
    print(f"  {s['f14']}: {s['f3']:+.2f}% (成交{s.get('f6',0)/1e8:.1f}亿)")
```

## 已知限制

| 能力 | 状态 | 替代方案 |
|------|------|---------|
| 指数/板块/概念行情 | ✅ 完全可用 | — |
| 涨跌停家数 | ✅ 可通过全市场数据推导 | — |
| 全市场量能 | ✅ 通过指数级 f20 汇总 | — |
| 昨日同比 | ✅ 结合 AKShare 日K线 | `ak.stock_zh_index_daily_em("sh000001")` |
| 北向资金 | ❌ 盘中不可用 | 标注缺失 |
| 个股深度盘口 | ⚠️ 可用但字段不全 | 脚本失败时更适合做宏观分析 |
| 板块资金流向(主力净流入) | ❌ 需不同端点 | 暂使用涨跌幅+成交额替代判断 |

## 与 AKShare 的差异

| 维度 | AKShare | HTTP API 直连 |
|------|---------|---------------|
| 行业板块 | 返回 `['item','value']`（2026-07 起失效） | 正确返回56个行业 |
| 知识板块 | 同上失效 | 正确返回200+概念 |
| 北向资金 | `stock_hsgt_north_net_flow_in_em` 被移除 | 不适用（无此端点） |
| 日K线 | 可用 (`stock_zh_index_daily_em`) | 需额外调用 |
| 速度 | 慢（含数据清洗） | 快（原始 JSON） |
| 依赖 | AKShare + pandas | 仅 requests |

## 行为回归（2026-08-11 实测）

2026-08-11 11:20-11:30 午盘前窗口观测到与 07-24 记录相反/新增的行为：

1. **`cb` 参数不再必需**：`clist/get` 板块榜请求**不带 `cb` 直接返回纯 JSON**（`{"rc":0,"data":...}`，非 JSONP）。与 07-24"必须带 cb"记录矛盾。**建议兼容两种响应格式**：先检测 `JQ(` 前缀再剥离，否则直接 json.loads。
2. **`Remote end closed connection without response` 间歇失败**：连续两次 `clist/get`（涨幅榜→跌幅榜）中，第二次请求失败（urllib `Remote end closed connection without response`）。**修复：加 `Referer: https://quote.eastmoney.com/` 头 + 重试 2-3 次（间隔 1.5-2s）**，第三次成功。同样的请求带 `cb=JQ` 与否均可。
3. **`push2his` 日K端点（`push2his.eastmoney.com/api/qt/stock/kline/get`）连续失败**：同一窗口 3 次重试全挂（均 `Remote end closed`）。**该端点不可靠，昨日量能基数改用 Tencent 成交量比率法**（见 `references/tencent-finance-api-fallback.md` 量能预估小节），或腾讯日K成交量做比率推算，不要死磕 push2his。
