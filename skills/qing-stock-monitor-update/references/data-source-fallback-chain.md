# 数据源降级与备用获取方案

> 当 `fetch_stock_data.py` 返回 `degraded: true` 或指定标的无法获取价格时的备用方案。

---

## 问题场景

- `fetch_stock_data.py` 对指定标的返回 `errors: ["No quote data"]`
- akshare 连接超时（`Connection aborted`, `RemoteDisconnected`）
- 东方财富 API 返回空数据
- venv 中 pip 缺失导致无法安装 akshare

---

## 备用方案链（按优先级）

### 方案 1：腾讯财经 API（curl，无需 Python 包）

```bash
# 获取实时行情，支持批量（最多约 60 只）
curl -s "http://qt.gtimg.cn/q=sz300054,sh688515,sh601138,sz002384,sz000807"
```

**返回格式**：`v_code="market~name~code~latest~prev_close~open~..."`

**字段位置**：
- `~` 分隔，字段 3=code, 字段 4=latest(最新价), 字段 5=prev_close(昨收), 字段 6=open(开盘)
- 涨跌幅需手动计算：`(latest - prev_close) / prev_close * 100`

**Python 解析示例**：
```python
import urllib.request

def get_tencent_quotes(codes):
    """codes: list like ['sz300054', 'sh688515']"""
    url = f"http://qt.gtimg.cn/q={','.join(codes)}"
    data = urllib.request.urlopen(url).read().decode('gb2312', errors='ignore')
    results = {}
    for line in data.strip().split(';'):
        if not line.strip():
            continue
        content = line.split('="')[1].rstrip('"')
        parts = content.split('~')
        if len(parts) >= 6:
            code = parts[2]
            results[code] = {
                'name': parts[1],
                'latest': float(parts[3]),
                'prev_close': float(parts[4]),
                'open': float(parts[5]),
                'pct_change': round((float(parts[3]) - float(parts[4])) / float(parts[4]) * 100, 2)
            }
    return results

# 使用
quotes = get_tencent_quotes(['sz300054', 'sh688515', 'sh601138', 'sz002384', 'sz000807'])
for code, info in quotes.items():
    print(f"{code}: {info['latest']} ({info['pct_change']}%)")
```

**优点**：
- 无需安装任何 Python 包
- 响应快，支持批量
- 数据实时

**缺点**：
- 返回数据为 GB2312 编码，需解码
- name 字段可能有乱码（不影响价格数据）
- 无 K 线、无主力资金数据

---

### 方案 2：修复 venv 安装 akshare

当 venv 中缺少 pip 或 akshare 时：

```bash
# 1. 安装 pip 到 venv
curl -sS https://bootstrap.pypa.io/get-pip.py | /home/ubuntu/.hermes/hermes-agent/venv/bin/python3 -

# 2. 安装 akshare + matplotlib
/home/ubuntu/.hermes/hermes-agent/venv/bin/python3 -m pip install akshare matplotlib --quiet

# 3. 验证
/home/ubuntu/.hermes/hermes-agent/venv/bin/python3 -c "import akshare; print('OK')"
```

**注意**：
- 系统 pip（`/usr/bin/pip3`）对应 Python 3.12，venv 中的是 Python 3.11
- 必须用 venv 的 python 运行 `get-pip.py`，不能用系统 pip
- 安装后 akshare 仍可能因网络问题连接超时

---

### 方案 3：glmv-stock-analyst 脚本（需 matplotlib）

```bash
cd ~/learning-investment-strategies
/usr/bin/python3 skills/qing-stock-analysis/vendor/glmv-stock-analyst/scripts/fetch_all.py 300054
```

**输出位置**：`stock_data_output/300054_YYYYMMDD_HHMM/`
- `data.json`：完整数据
- `summary.json`：摘要
- `kline_em.png`：日 K 线图

**注意**：
- 需要 matplotlib（`pip install matplotlib`）
- 可能因网络超时返回空数据
- 输出目录需手动查找

---

### 方案 4：新浪板块成分股 API（curl，无需 Python 包）

用于获取板块内个股排名和量化地位判断：

```bash
# 获取板块列表（概念）
curl -s 'http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class' | iconv -f gbk -t utf-8

# 获取某板块成分股（按涨幅排序）
curl -s 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=100&sort=changepercent&asc=0&node=gn_hwqc' | iconv -f gbk -t utf-8
```

**返回字段**：code, name, changepercent, mktcap, turnoverratio, trade, volume...

**用途**：
- 建立个股→板块映射缓存：`scripts/build_sector_mapping.py`
- 实时判断个股在板块内的地位（龙头/中军/趋势/跟风）

**注意**：
- 接口有频率限制，连续请求间隔需 ≥1.5 秒
- 频繁请求会被 IP 限流（3-5 分钟解封）
- 建议通过本地缓存（`config/stock_monitor/stock_sector_mapping.json`）查询，每日重建一次

---

### 方案 5：东方财富直接 API（curl）

```bash
# 单只标的（深市 sz 前缀用 secid=0.，沪市 sh 前缀用 secid=1.）
curl -s "https://push2.eastmoney.com/api/qt/stock/get?secid=0.300054&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f170"
```

**字段映射**：
- `f43` = 最新价 × 100（需除以 100）
- `f44` = 最高价 × 100
- `f45` = 最低价 × 100
- `f46` = 开盘价 × 100
- `f47` = 成交量（手）
- `f48` = 成交额（元）
- `f57` = 股票代码
- `f58` = 股票名称
- `f60` = 昨收 × 100
- `f170` = 涨跌额 × 100（注意：不是涨跌幅百分比，需手动计算 `(f43-f60)/f60*100`）

**注意**：
- 此 API 在非交易时段可能返回空数据或缓存数据
- **IP 限流警告**：连续高频请求（如脚本循环批量调用）会触发东财服务器限流，返回空响应 `{}` 或连接重置。限流后需等待 5-10 分钟恢复
- **推荐做法**：单脚本内调用东财 API 时加入 `sleep 1-3` 间隔；若需批量获取多只标的，优先使用腾讯 API（方案 1）或新浪 API（方案 4），它们对批量请求更友好
- **指数 K 线历史数据**：`push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000985&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&lmt=5` 可获取近 N 日 K 线，限流风险低于实时行情接口

---

### 方案 6：新浪实时行情 API（curl，支持批量）

```bash
# 批量获取（最多约 30 只，逗号分隔）
curl -s "https://hq.sinajs.cn/list=sh603228,sz300408,sz300054,sz300433,sh600584" -H "Referer: https://finance.sina.com.cn" | iconv -f gb2312 -t utf-8
```

**返回格式**：`var hq_str_CODE="name,pre_close,latest,high,low,volume,amount,...,date,time"`

**字段位置**（逗号分隔）：
- `name` = 股票名称
- `pre_close` = 昨收
- `latest` = 最新价
- `high` = 最高价
- `low` = 最低价
- `volume` = 成交量（股）
- `amount` = 成交额（元）
- 末尾 `date,time` = 数据时间戳

**涨跌幅计算**：`(latest - pre_close) / pre_close * 100`

**优点**：
- 支持批量查询（一次最多约 30 只）
- 数据实时，无明显的 IP 限流（比东财更稳定）
- 返回数据包含时间戳，可验证数据新鲜度

**缺点**：
- 需要 `Referer` header（`https://finance.sina.com.cn`）
- 需要 GB2312 → UTF-8 转码
- 指数数据（如 `sh000985` 中证全指）可能返回空值

**注意**：
- 批量查询时标的数量过多会导致返回截断，建议每批 ≤ 30 只
- 科创板（688 开头）和创业板（300 开头）数据均可正常返回

---

## 决策流程

```
fetch_stock_data.py 失败？
  ├── 是 → 检查是否为 venv pip 问题
  │         ├── 是 → 方案 2（安装 pip + akshare）
  │         └── 否 → 尝试方案 1（腾讯 API，curl）
  │               ├── 成功 → 使用腾讯数据
  │               └── 失败 → 方案 4（东方财富 curl）
  └── 否 → 正常使用 fetch_stock_data.py 输出
```

---

## 关键纪律

1. **绝不编造价格**：数据源全部降级时，诚实说明"无法获取实时价格"，提供计算规则，不编造数字。
2. **优先腾讯 API**：curl 方案最稳定，无需安装包，适合紧急获取价格。
3. **标注数据来源**：使用备用方案时，在 `meta.data_source` 中标注 `"tencent_fallback"` 或 `"manual"`。
