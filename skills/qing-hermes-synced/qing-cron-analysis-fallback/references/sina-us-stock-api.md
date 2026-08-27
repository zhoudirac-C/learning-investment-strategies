# Sina US Stock API — 美股隔夜/盘前直连

> 验证日期：2026-07-23 09:28 BJT（集合竞价后开盘前分析）

## 为什么需要这个

`qing-cron-analysis-fallback` 的现有降级路径（AKShare → EastMoney HTTP → Sina A股 → Tencent Finance → claims-only）均不覆盖 **美股隔夜行情**。当开盘分析需要回答「隔夜外围如何」时，此路径提供美股盘前/隔夜收盘数据。

**核心价值**：在 1-2 秒内判断 GOOG 财报后市场反应、NVDA/SMCI 走势、纳指整体方向，无需任何 Python 包或外部依赖。

## 核心端点

```
GET https://hq.sinajs.cn/list=gb_qqq,gb_goog,gb_nvda,gb_smci,gb_aapl,gb_amzn,gb_tsla
```

**必须携带头**：
```
Referer: https://finance.sina.com.cn
```

**代码格式**：`gb_` + 美股代码小写（qqq, goog, nvda, smci, aapl, amzn, tsla, msft, amd, meta 等）

## 返回格式（GBK 编码）

```
var hq_str_gb_goog="谷歌,341.9100,-1.24,2026-07-23 09:30:09,-4.2800,347.1800,349.4500,341.6400,404.2500,187.8500,23273840,16189049,4159677089404,13.25,25.800000,0.00,0.00,0.00,0.00,12166000086,71,331.9079,-2.93,-10.00,Jul 22 07:59PM EDT,Jul 22 04:00PM EDT,346.1900,7061530,1,2026,7987296941.0000,353.0000,315.3750,2386492878.8967,341.9100,346.1900";
```

### 关键字段索引（按逗号分割）

| 索引 | 字段 | 说明 | 示例 |
|------|------|------|------|
| parts[0] | 名称 | 中文名称 | 谷歌 |
| **parts[1]** | **当前价** | 盘前/实时价格 | 341.9100 |
| **parts[2]** | **涨跌幅%** | 相对昨收的百分比变化 | -1.24 |
| parts[3] | 日期时间 | 北京时间 | 2026-07-23 09:30:09 |
| parts[4] | 涨跌额 | 绝对变化 | -4.2800 |
| parts[5] | 今日开盘 | 盘前开盘价 | 347.1800 |
| parts[6] | 今日最高 | 盘前最高 | 349.4500 |
| parts[7] | 今日最低 | 盘前最低 | 341.6400 |
| parts[8] | 52周最高 | — | 404.2500 |
| parts[9] | 52周最低 | — | 187.8500 |
| parts[10] | 成交量 | 盘前/实时成交量 | 23273840 |
| parts[11] | 成交额 | 盘前/实时成交额(元) | 16189049 |
| parts[22] | 昨收价(备用) | 有时是折合价 | 331.9079 |
| parts[31] | **昨收(收盘价)** | **前一交易日收盘价** | 346.1900 |

> **⚠️ 验证方法**：用 parts[31]（昨收价）与 parts[1]（当前价）交叉验证涨跌幅：
> `(341.91 - 346.19) / 346.19 = -1.24%` ✅ 与 parts[2] 一致

### 推荐字段提取方式（Python）

```python
import urllib.request

codes = "gb_qqq,gb_goog,gb_nvda,gb_smci,gb_aapl,gb_amzn,gb_tsla"
url = f"https://hq.sinajs.cn/list={codes}"
req = urllib.request.Request(url, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
})
data = urllib.request.urlopen(req, timeout=10).read().decode("gbk", errors="ignore")

for line in data.strip().split("\n"):
    line = line.strip()
    if not line or "=" not in line:
        continue
    var_str, val = line.split("=", 1)
    val = val.strip('"')
    parts = val.split(",")
    if len(parts) < 32:
        continue
    name = parts[0]
    price = parts[1]
    pct = parts[2]
    prev_close = parts[31]  # 前一交易日收盘价
    dt = parts[3]
    print(f"{name}: {price} ({pct}%) 昨收{prev_close} [{dt}]")
```

## 常见美股代码对照

| 新浪代码 | 标的 | 说明 |
|---------|------|------|
| `gb_qqq` | 纳指100 ETF | 纳指整体方向 |
| `gb_spy` | 标普500 ETF | 大盘方向 |
| `gb_dia` | 道琼斯 ETF | 蓝筹方向 |
| `gb_goog` | 谷歌 | **AI 财报核心** |
| `gb_nvda` | 英伟达 | AI 算力需求指标 |
| `gb_smci` | 超微电脑 | 服务器景气度 |
| `gb_aapl` | 苹果 | 消费电子 |
| `gb_amzn` | 亚马逊 | 云/AI 应用 |
| `gb_msft` | 微软 | AI 平台 |
| `gb_tsla` | 特斯拉 | 新能源/机器人 |
| `gb_amd` | AMD | AI 芯片第二极 |
| `gb_meta` | Meta | AI 广告/应用 |
| `gb_avgo` | 博通 | 网络/AI 芯片 |

## 已知限制

| 能力 | 状态 | 替代 |
|------|------|------|
| 美股隔夜收盘价 | ✅ 盘前可用 | — |
| 美股盘前实时(09:00-16:30 BJT) | ✅ | — |
| 美股盘中(夏令时 21:30-04:00 BJT) | ✅ | — |
| 历史K线 | ❌ | 不提供 |
| 财报数据 | ❌ | 需其他来源 |

## 适用场景

| 时间窗口 | 推荐用途 |
|---------|---------|
| 09:25-09:30 集合竞价后开盘前 | 检查隔夜外围（GOOG 财报反应、纳指方向） |
| 13:00-13:10 午后开盘 | 检查美股盘前（夏令时已开盘） |
| 15:00-17:00 收盘复盘 | 汇总隔夜数据用于下日预判 |

## 与 A 股 Tencent API 的组合使用

A 股开盘前（09:25-09:30）的完整数据采集流程：

```bash
# Step 1: Sina US — 美股盘前/隔夜行情（~1s）
curl -s -H "Referer: https://finance.sina.com.cn" \
  "https://hq.sinajs.cn/list=gb_qqq,gb_goog,gb_nvda,gb_smci" \
  | iconv -f GBK -t UTF-8 | python3 -c "[...解析...]"

# Step 2: Tencent — A股开盘指数+个股（~0.5s）
curl -s "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000688,sz000938,sz002409,sz001258,sz002812" \
  | python3 -c "
import sys
raw = sys.stdin.buffer.read().decode('gbk', errors='ignore')
for line in raw.strip().split(';'):
    parts = line.split('~')
    if len(parts) < 38: continue
    print(f\"{parts[1]}: {parts[3]} ({parts[32]}%)\")
"

# Step 3: Neo4j claims — 完整 context（~2s）
# mcp__neo4j__get_recent_claims(days=3)
```

此组合可在 **3 秒内**完成开盘分析的全部数据采集。

## 参考

- `qing-cron-analysis-fallback/SKILL.md` — 父级 fallback skill
- `references/sina-api-fallback.md` — Sina A股实时行情文档
- `references/tencent-finance-api-fallback.md` — Tencent A股行情文档
