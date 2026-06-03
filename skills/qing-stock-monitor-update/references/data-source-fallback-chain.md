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

### 方案 4：东方财富直接 API（curl）

```bash
# 单只标的
curl -s "https://push2.eastmoney.com/api/qt/stock/get?secid=0.300054&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f170"
```

**字段映射**：
- `f43` = 最新价 × 100（需除以 100）
- `f44` = 最高价 × 100
- `f45` = 最低价 × 100
- `f46` = 开盘价 × 100
- `f47` = 成交量
- `f48` = 成交额
- `f57` = 股票代码
- `f58` = 股票名称
- `f60` = 昨收 × 100
- `f170` = 涨跌幅

**注意**：此 API 在非交易时段可能返回空数据或缓存数据。

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
