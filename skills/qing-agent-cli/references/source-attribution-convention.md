# Qing-Agent 来源标注规范

## 背景

用户明确要求区分 Qing-Agent 输出和 Hermes Agent 自身分析。当 Hermes Agent 调用 Qing-Agent 的 `/chat` 端点后，Qing-Agent 的回复必须带有明确来源标识。

## 规范

### Qing-Agent 输出格式

`/chat` 端点的 prompt 中已内置格式要求：

```
7. 【输出格式】回复开头必须标注：'[Qing-Agent 分析]'，然后空一行再写正文
```

这导致 Qing-Agent 的所有回复自动以 `[Qing-Agent 分析]` 开头：

```
[Qing-Agent 分析]

中国长城今天收盘17.05，盘中最低16.98...
```

### Hermes Agent 的呈现方式

当 Hermes Agent 调用 Qing-Agent 后，直接呈现 `reply` 字段内容，不做额外包装：

```python
result = terminal("curl -s -X POST http://127.0.0.1:8000/chat ...")
# 解析 JSON 提取 reply
reply = json.loads(result)["reply"]
# 直接输出 reply（已包含 [Qing-Agent 分析] 前缀）
```

### 何时不加前缀

- Hermes Agent **自身分析**（如读取 positions.yaml 后的持仓计算、成本分析）→ **不加** `[Qing-Agent 分析]`
- Qing-Agent **直接返回**的分析 → **自动加** `[Qing-Agent 分析]`（由 prompt 控制）

### 混合场景

当 Hermes Agent 先调用 Qing-Agent 获取分析，再补充自身判断时：

```
[Qing-Agent 分析]

（Qing-Agent 的原始回复...）

---

**补充说明**（Hermes Agent）：

基于你的持仓配置（positions.yaml）：
- 成本18.07，当前17.05，浮亏5.7%
- 仓位约1%，清仓线15.8
- 建议：按计划执行，不恐慌，不幻想
```

## 实现细节

### Prompt 中的格式要求位置

在 `src/qing_investment/agent/main.py` 的 `/chat` 端点中，prompt_lines 列表包含：

```python
prompt_lines = [
    "你是青枫浦上Q的助手，风格犀利但不劝赌，不用机构研报腔。",
    "",
    "【核心原则】",
    "1. 所有判断必须基于【实时行情数据】，不能基于历史观点",
    ...
    "7. 【输出格式】回复开头必须标注：'[Qing-Agent 分析]'，然后空一行再写正文",
    "",
    *context_parts,
    f"\n用户：{req.message}\n",
    "请直接回复：",
]
```

### 验证方法

```bash
# 测试回复是否包含前缀
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "今天大盘怎么样", "session_id": "test"}' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d['reply'][:50])"

# 预期输出开头: [Qing-Agent 分析]
```

## 历史K线数据获取

### 功能

`/chat` 端点在检测到个股查询时，自动获取**20日历史K线**数据：

- 数据源：腾讯 `web.ifzq.gtimg.cn/appstock/app/fqkline/get`
- 返回字段：日期、开盘、收盘、最高、最低、成交量、涨跌幅
- 格式化：表格形式注入 prompt

### 代码位置

```
src/qing_investment/agent/tools/stock_data.py
  - fetch_stock_kline(code, days=20) → list[dict]
  - format_kline_for_prompt(klines) → str

src/qing_investment/agent/main.py
  - /chat 端点中 stock_klines 获取逻辑
```

### 触发条件

个股查询检测关键词：
```python
is_stock_query = any(kw in query_lower for kw in [
    "股", "走势", "分析", "低点", "高点", "买入", "卖出",
    "抄底", "减仓", "加仓", "持仓", "套牢", "解套",
    "止损", "止盈", "目标价", "支撑", "压力"
])
```

### K线数据格式示例

```
日期        开盘    收盘    最高    最低    成交量(万手)  涨跌%
-----------------------------------------------------------------
2026-05-11  24.52   23.40   23.25   24.77     572.9      +1.34%
2026-05-12  23.52   25.36   23.42   25.74     689.5      +8.38%
...
统计: 区间高点=25.74 区间低点=17.74 区间振幅=45.1%
      最新价=17.05 距高点回撤=33.8% 5日均量=189.3万手
```

## 故障排查

### 回复没有 [Qing-Agent 分析] 前缀

1. 检查服务是否重启（修改 prompt 后必须重启）
2. 检查 `main.py` 中 prompt_lines 是否包含格式要求
3. 检查 LLM 是否遵循指令（某些模型可能忽略格式要求）

### K线数据为空

1. 检查日期范围：腾讯接口需要正确的 `start_date` 和 `end_date`
2. 检查代码格式：`sz000066` 或 `sh600519`
3. 检查网络：`curl -s "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz000066,day,2026-05-01,2026-06-06,500,qfq"`
