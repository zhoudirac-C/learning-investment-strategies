# /chat 端点实时数据获取实现参考

## 背景

Qing-Agent 的 `/chat` 端点原本只依赖用户消息中的知识和历史 claims，不主动获取实时行情。这导致当用户问"今天大盘怎么样"时，模型要么编造数据，要么只能引用过时的 claims。

2025-06-06 的修改让 `/chat` 根据查询类型自动获取实时数据：
- 大盘/市场/指数查询 → 自动获取上证指数、深证成指、创业板、科创50
- 板块/行业/概念查询 → 获取指数 + 板块领涨数据
- 个股查询（含6位代码）→ 获取该股票实时行情

## 数据来源选择

### 首选：腾讯 `qt.gtimg.cn`（当前使用）

```python
url = f"https://qt.gtimg.cn/q={','.join(codes)}"
# codes 格式: ["sh000001", "sz399001", "sz399006", "sz000066"]
```

**优点**：
- 在腾讯云 2C/8G 实例上稳定可用
- 不依赖 akshare 的复杂解析逻辑
- 响应快（<500ms）
- 支持指数 + 个股统一接口

**返回格式**：GBK 编码的 JavaScript 变量赋值，用 `~` 分隔字段：
```
v_sh000001="1~上证指数~000001~4027.74~4057.78~4044.83~...~...";
```

**关键字段索引**：
- `parts[1]` = 名称
- `parts[2]` = 代码
- `parts[3]` = 当前价
- `parts[4]` = 昨收
- `parts[5]` = 开盘价
- `parts[32]` = 涨跌幅(%)
- `parts[33]` = 最高价
- `parts[34]` = 最低价
- `parts[36]` = 成交量（股）
- `parts[37]` = 成交额（元）

### 备选：东方财富 push2 API

```python
url = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    "?fltt=2&invt=2"
    "&fields=f12,f13,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
    "&secids=1.000001,0.399001,0.399006,0.000066"
)
```

**问题**：在腾讯云上频繁出现 `RemoteDisconnected('Remote end closed connection without response')`，可能是 IP 被限流或防火墙策略导致。因此不作为默认源。

### 备选：akshare

**问题**：`akshare.stock_zh_a_spot_em()` 等接口同样依赖东方财富，在腾讯云上连接被重置。且 akshare 依赖 py_mini_racer，有额外安装负担。

## 代码结构

```
src/qing_investment/agent/tools/stock_data.py   # 个股/指数数据获取
src/qing_investment/agent/tools/sector_data.py  # 板块数据获取（已有）
src/qing_investment/agent/main.py               # /chat 端点数据获取逻辑
```

### stock_data.py 接口

```python
from qing_investment.agent.tools.stock_data import (
    fetch_stock_quotes,   # 批量获取
    fetch_index_quotes,   # 获取主要指数
    fetch_single_stock,   # 单只股票
)

# 批量获取
quotes = fetch_stock_quotes(["sh000001", "sz399001", "sz000066"])

# 获取指数
indices = fetch_index_quotes()
# 返回: 上证、深成指、创业板、科创50

# 单股（自动补 sh/sz 前缀）
stock = fetch_single_stock("000066")   # → sz000066
stock = fetch_single_stock("600519")   # → sh600519
```

### /chat 端点的查询类型检测

```python
query_lower = req.message.lower()
is_market_query = any(kw in query_lower for kw in [
    "大盘", "市场", "行情", "指数", "上证", "创业板", "科创"
])
is_sector_query = any(kw in query_lower for kw in [
    "板块", "行业", "概念"
])

import re
stock_code_match = re.search(r'(\d{6})', req.message)
fetched_stock_code = stock_code_match.group(1) if stock_code_match else None
```

### 数据获取策略

```python
market_snapshot: dict = {"quotes": []}
external_sector_boards: dict = {"available": False}

# 1. 市场/板块查询，或没有个股代码时，获取指数
if is_market_query or is_sector_query or not fetched_stock_code:
    index_quotes = fetch_index_quotes()
    market_snapshot["quotes"] = index_quotes

# 2. 市场/板块查询时，获取板块数据
if is_sector_query or is_market_query:
    sector_data = get_sector_strength_snapshot(top_n=15)
    external_sector_boards = {"available": True, **sector_data}

# 3. 有个股代码时，获取个股数据
if fetched_stock_code:
    stock_quote = fetch_single_stock(fetched_stock_code)
    if stock_quote:
        market_snapshot["quotes"].append(stock_quote)
```

## Prompt 构建要点

实时数据必须在 prompt 中明确标记为**主要分析依据**，历史 claims 标记为**仅供参考**：

```
【实时行情数据】（✅ 主要分析依据）
- 个股/指数行情:
  上证指数(000001): 开4044.83 收4027.74 高4078.93 低4015.06 涨跌-0.74%
  ...
- 板块数据:
  宽带提速: 1.90%
  ...

【博主分析方法论】（仅供参考UP的分析框架和概念定义）
...

【博主历史观点卡】（⚠️ 历史观点，仅供参考，不得作为当前判断依据）
...
```

核心原则：
1. 所有判断必须基于【实时行情数据】
2. 不得引用 claim ID 支持当前观点
3. 方法论概念（冰点期、劣性轮动等）可以引用，但具体历史观点必须验证

## 验证方法

```bash
# 测试1：大盘查询
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "今天大盘怎么样", "session_id": "test"}'

# 测试2：个股查询
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "000066走势如何", "session_id": "test"}'

# 测试3：板块查询
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "半导体板块怎么样", "session_id": "test"}'
```

通过标准：
- 回复包含实时行情数据
- 不引用 claim ID
- 基于当前数据分析，不编造

## 故障排查

### 数据获取为空

1. 检查网络：`curl -v https://qt.gtimg.cn/q=sh000001`
2. 检查编码：腾讯返回 GBK，必须用 `decode("gbk", errors="ignore")`
3. 检查代码格式：`sh6xxxxx` / `sz0xxxxx` / `sz3xxxxx` / `sh688xxx`

### 板块数据获取慢

`get_sector_strength_snapshot` 调用 akshare 的板块接口，可能需要 10-20 秒。如果超时，可以调低 `top_n` 或增加缓存。

### 服务启动后未生效

`/chat` 端点的数据获取逻辑在 `main.py` 中，修改后必须重启 uvicorn 服务：

```bash
pkill -9 -f "uvicorn.*qing_investment"
cd ~/learning-investment-strategies
PYTHONPATH=src .venv/bin/python -m uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000
```
