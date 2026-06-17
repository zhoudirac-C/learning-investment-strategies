# 市场指数配置与数据注入

> 记录系统当前拉取的市场指数、如何新增、以及已知限制。

## 当前配置

| 指数 | 代码 | 腾讯格式 | 注入位置 |
|------|------|---------|---------|
| 上证指数 | 000001 | `1.000001` | stock_monitor.py + stock_data.py |
| 深证成指 | 399001 | `0.399001` | stock_monitor.py + stock_data.py |
| 创业板指 | 399006 | `0.399006` | stock_monitor.py + stock_data.py |
| 科创50 | 000688 | `1.000688` | stock_monitor.py + stock_data.py |
| 全A指数 | 000985 | `1.000985` | stock_monitor.py + stock_data.py |

## 全A指数说明

UP（青枫浦上Q）在复盘/午盘/动态中频繁使用「全A指数」判断市场广度（如"全A指数未出中阳线""全A仍偏弱"）。

- **同花顺全A(883657)**：UP 使用的版本，但该指数为同花顺客户端私有数据，**不提供公开 HTTP API**（腾讯/东方财富/同花顺接口均返回 404 或 none_match）
- **中证全指(000985)**：交易所官方指数，同样覆盖全A市场，腾讯 API 原生支持（`sh000985`）。走势与同花顺全A高度一致，作为**功能等价替代**
- **国证A指(399317)**：备选方案，腾讯 API 支持（`sz399317`），当前未启用

## 新增指数的步骤

需要同步修改两个文件：

### 1. `src/qing_investment/stock_monitor.py` — cron 管线
```python
MARKET_INDEXES = {
    "上证指数": "1.000001",
    ...
    "新指数名": "1.XXXXXX",   # 1=上证, 0=深证
}
```
影响：15 个 cron job 拉行情时自动包含新指数，`collect_quote_targets()` 消费。

### 2. `src/qing_investment/agent/tools/stock_data.py` — Qing-Agent /chat 管线
```python
def fetch_index_quotes() -> list[dict]:
    return fetch_stock_quotes(["sh000001", ..., "shXXXXXX"])
```
影响：用户通过 Qing-Agent `/chat` 问大盘时自动包含新指数。

### 3. 重启 Agent
修改代码后必须重启 uvicorn 加载新代码。

## 验证

```bash
# 腾讯 API 测试
curl -s "http://qt.gtimg.cn/q=sh000985" | iconv -f gb2312 -t utf-8

# 验证 cron 管线（不触发提醒）
cd ~/learning-investment-strategies
.venv/bin/python -m qing_investment.stock_monitor --status
```
