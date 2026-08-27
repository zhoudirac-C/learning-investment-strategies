# Sina Finance API — 实时 A 股数据直连（路径 C）

> 适用场景：AKShare + EastMoney 均不可用时，作为稳定中间降级选项（路径 C）。
> 已验证：2026-07-22 14:40 尾盘监控中成功使用。

## 为什么需要这个

降级链中 AKShare（路径 B）和 EastMoney HTTP（路径 A）有各自的功能优势，但在以下场景两者同时失效：

1. **AKShare**：`Connection aborted`（EastMoney 服务端断开）或 huggingface-hub 版本冲突
2. **EastMoney push2**：返回空响应或 `RemoteDisconnected`（限流/封禁）

此时，Sina API 作为**纯 HTTP 降级**选项，不需安装任何 Python 包，返回结构简单易解析。

## 与路径 D（Tencent API）的定位差异

| 维度 | Sina API（路径 C） | Tencent API（路径 D） |
|------|-------------------|----------------------|
| 端点 | `hq.sinajs.cn/list=` | `qt.gtimg.cn/q=` |
| 编码 | GBK（可通过 iconv 或 Python decode 处理） | GBK |
| 响应格式 | 类 CSV（逗号分隔） | 类 CSV（波浪线分隔） |
| 指数数据 | ✅ 完整（含昨收、开高低收、量、额） | ✅ 完整 |
| 个股数据 | ✅ 完整（含昨收/今开/高低/量额/盘口） | ✅ 完整 |
| 涨跌幅 | ❌ 不直接提供（需手动计算） | ✅ 直接提供（parts[32]） |
| 日K线（历史量能） | ❌ 不支持 | ✅ Tencent 有独立日K线端点 |
| 速度 | 快（~0.5-1s） | 快（~0.5-1s） |
| 稳定性 | ✅ 极稳定，未出现过限流 | ✅ 极稳定 |
| 编码处理 | GBK → UTF-8 需 iconv 或 Python .decode('gbk') | 同左 |

**核心取舍**：Sina 提供昨收价（便于手动算涨跌幅），Tencent 直接提供涨跌幅且拥有独立的日K线端点。**推荐组合使用**：Sina 拿实时行情 + Tencent 拿历史日K线对比量能。

## 核心端点

```
GET https://hq.sinajs.cn/list={codes}
```

**参数**：逗号分隔的代码列表。

**代码格式规则**：
- 上交所主板（6xxxxx）：`sh` + 代码（如 `sh600584`）
- 上交所科创板（688xxx）：`sh` + 代码（如 `sh688525`）
- 上证指数：`sh000001`
- 深交所主板/中小板（00xxxx）：`sz` + 代码（如 `sz002409`）
- 深交所创业板（30xxxx）：`sz` + 代码（如 `sz300308`）
- 深证指数：`sz` 前缀（如 `sz399001`, `sz399006`）

**完整示例**（同时查询指数 + 个股）：
```bash
curl -s -H "Referer: https://finance.sina.com.cn" \
  "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000688,sz002409,sz002281"
```

## 返回格式

### 原始输出

```
var hq_str_sh000001="上证指数,3839.6654,3864.3671,3860.7789,3884.4352,3839.6654,0,0,568568814,1174989642855,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-22,14:40:32,00,";
var hq_str_sz002409="雅克科技,146.420,143.550,150.030,157.910,146.400,150.030,150.040,46724398,7117729007.370,[...盘口字段...],2026-07-22,14:40:42,00";
```

### 指数/个股通用字段索引（按逗号分割后的 parts）

| 索引 | 字段 | 说明 |
|------|------|------|
| parts[0] | 名称 | 中文名称（如"上证指数""雅克科技"） |
| parts[1] | 开盘价 | 今日开盘价 |
| **parts[2]** | **昨收价** | **上一交易日收盘价（涨跌幅计算基准）** |
| parts[3] | 当前价 | 最新成交价 |
| parts[4] | 最高价 | 日内最高 |
| parts[5] | 最低价 | 日内最低 |
| parts[8] | 成交量（手） | 上证指数单位是亿手？个股为手 |
| parts[9] | 成交额（元） | 需除以 1e8 得亿 |
| parts[30] | 日期 | 如 `2026-07-22` |
| parts[31] | 时间 | 如 `14:40:32` |

> **⚠️ 关键**：Sina 不直接提供涨跌幅字段。必须用 `(当前价 - 昨收价) / 昨收价 * 100` 手动计算。parts[2] = 昨收价，parts[3] = 当前价。

### 个股额外盘口字段（parts[10]-parts[29]）

这些是买五卖五的盘口数据，通常不需要解析用于宏观分析：

| 索引 | 字段 |
|------|------|
| 10 | 买一价 |
| 11 | 买一量 |
| 12-19 | 买二至卖五（交替价量） |
| 20-29 | 卖一价至卖五量（交替或顺序） |

**建议**：日内监控时忽略这些盘口数据，仅用 0-9 的通用字段。

## 编码处理

Sina API 返回 **GBK 编码**（含部分高字节中文）。两种处理方式：

### 方式1：iconv（终端管道，推荐）
```bash
curl -s -H "Referer: https://finance.sina.com.cn" "https://hq.sinajs.cn/list=sh000001,sz399001" \
  | iconv -f GBK -t UTF-8
```

### 方式2：Python decode（脚本内）
```python
import urllib.request, urllib.parse

url = "https://hq.sinajs.cn/list=" + urllib.parse.quote("sh000001,sz399001,sz399006")
req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
with urllib.request.urlopen(req, timeout=15) as resp:
    raw = resp.read().decode("gbk", errors="ignore")
```

## 已验证的调用模式（2026-07-22 尾盘监控确认）

### 模式1：指数行情完整分析（含涨跌幅手动计算）

```bash
curl -s -H "Referer: https://finance.sina.com.cn" \
  "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000688,sh000300,sh000016,sz399905,sz399852" \
  | iconv -f GBK -t UTF-8 \
  | python3 -c "
import sys
for line in sys.stdin:
    line = line.strip()
    if not line or not line.startswith('var hq_str_'): continue
    content = line.split('=\"')[1].rsplit('\",', 1)[0]
    parts = content.split(',')
    name = parts[0]
    open_p = float(parts[1])
    prev_close = float(parts[2])
    current = float(parts[3])
    high = float(parts[4])
    low = float(parts[5])
    amount = float(parts[9]) / 1e8  # 成交额（亿元）
    date = parts[30]; time = parts[31]
    change = current - prev_close
    change_pct = change / prev_close * 100
    print(f'{name: <10} 当前={current:>8.2f}  涨跌={change_pct:>+.2f}%  高={high:>8.2f}  低={low:>8.2f}  额={amount:>5.0f}亿  [{time}]')
"
```

### 模式2：Watchlist 个股批量行情（2026-07-22 尾盘验证）

```bash
curl -s -H "Referer: https://finance.sina.com.cn" \
  "https://hq.sinajs.cn/list=sz002409,sz002281,sz002812,sz300308,sh600584,sz002916,sh603005,sh688525,sz002432,sh603118" \
  | iconv -f GBK -t UTF-8 \
  | python3 -c "
import sys
for line in sys.stdin:
    if not line.startswith('var hq_str_'): continue
    code = line.split('var hq_str_')[1].split('=')[0]
    content = line.split('=\"')[1].rsplit('\",', 1)[0]
    parts = content.split(',')
    name = parts[0]
    prev_close = float(parts[2])
    current = float(parts[3])
    high = float(parts[4]); low = float(parts[5])
    amount = float(parts[9]) / 1e8
    change_pct = (current - prev_close) / prev_close * 100
    print(f'{name: <12} {code: >10}  当前={current:>8.2f}  涨跌={change_pct:>+6.2f}%  高={high:>8.2f}  低={low:>8.2f}  额={amount:>5.0f}亿')
"
```

### 模式3：指数 + 个股混合查询（单次请求即可，减轻 API 调用频率）

```bash
ALL_CODES="sh000001,sz399001,sz399006,sh000688,sh000300,sh000016"
ALL_STOCKS="sz002409,sz002281,sz002432,sh603118"
curl -s -H "Referer: https://finance.sina.com.cn" \
  "https://hq.sinajs.cn/list=${ALL_CODES},${ALL_STOCKS}" \
  | iconv -f GBK -t UTF-8 \
  | python3 -c "
import sys
lines = [l.strip() for l in sys.stdin if l.startswith('var hq_str_')]
print(f'总条目: {len(lines)}')
# 按需字典解析...
"
```

## 与 Tencent API 的混合使用模式（2026-07-22 验证）

**推荐组合**：Sina 拿实时行情 + Tencent 拿历史日K线对比量能。单次分析流程如下：

```bash
# Step 1: Sina — 指数+个股实时行情（~1秒）
curl -s -H "Referer: https://finance.sina.com.cn" \
  "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000688,sz002409,sz002281" \
  | iconv -f GBK -t UTF-8 | python3 -c "[...解析模式1/2...]"

# Step 2: Tencent — 日K线量能对比（~1秒）  
curl -s "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,,,10,qfq" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
for k in d['data']['sh000001']['day']:
    print(f'{k[0]}: 收={k[2]:>8}  量={float(k[5])/1e4:.1f}亿')
"
```

**为什么这样组合**：Sina 比 Tencent 更稳定地提供昨收价（parts[2]），适合涨跌幅手动计算；Tencent 的日K线端点（`web.ifzq.gtimg.cn`）是 Sina 缺失的重要补充。两者无功能重叠，组合使用信息最完整。

> **⚠️ 不能做的**：不要尝试 Sina 的行业板块/概念板块排名 API（`vip.stock.finance.sina.com.cn/q/go.php/vIndustryRank` 和 `vConceptRank`）。这些端点已永久失效，返回 `{"__ERROR": 0, "__ERRORMSG": "Invalid view go"}`，无法用于 A 股板块排行获取。板块排行必须走 EastMoney 或 AKShare。

## 没有的内容（相对于 EastMoney/AKShare）

| 能力 | Sina 是否支持 | 替代 |
|------|-------------|------|
| 行业板块排行 | ❌（端点已永久失效） | 需走 EastMoney 或 AKShare |
| 概念板块排行 | ❌（端点已永久失效） | 同上 |
| 涨跌停家数 | ❌ | 无法从该数据源推导 |
| 涨跌家数比 | ❌ | 无法推导 |
| 北向资金 | ❌ | 盘中通常不可用 |
| 历史K线 | ❌ | 用 Tencent API 补充 |
| 量比指标 | ❌ | 通过量能同比替代 |

## 适用场景优先级

| 场景 | 推荐路径 | 原因 |
|------|---------|------|
| 仅需指数实时行情 | **路径 C（Sina）** 或 路径 D（Tencent） | 最快，~0.5-1s |
| 需指数 + 日K线量能对比 | **Sina + Tencent 混合** | Sina 实时 + Tencent 历史 |
| 需个股批量报价 | **Sina** | 单次请求即可查询 20+ 标的 |
| 需板块排行 | 路径 A（EastMoney） | 唯一提供板块数据 |
| 需涨跌家数/涨跌停家数 | 路径 A（EastMoney） | 全市场模式可推导 |

## 参考

- `qing-cron-analysis-fallback/` SKILL.md — 父级 skill，含完整的降级分析框架
- `references/tencent-finance-api-fallback.md` — 路径 D（Tencent API）详细文档
- `references/eastmoney-direct-api-fallback.md` — 路径 A（EastMoney HTTP API）详细文档
