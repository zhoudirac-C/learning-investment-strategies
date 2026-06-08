# 股票代码查询 API 参考

> 用途：写 claim 时查询 A 股公司 6 位数字代码
> 更新日期：2026-06-08

## 东方财富搜索 API（推荐）

```
GET https://searchapi.eastmoney.com/api/suggest/get?input={公司名}&type=14&count=1
```

**参数**：
- `input`：公司中文名（需 URL 编码）
- `type=14`：A 股搜索
- `count=1`：只返回最匹配结果

**返回格式**：
```json
{
  "QuotationCodeTable": {
    "Data": [
      {
        "Code": "301061",
        "Name": "乔锋智能",
        "SecurityTypeName": "A股"
      }
    ]
  }
}
```

**Python 查询示例**：
```python
import urllib.request, urllib.parse, json

def get_stock_code(name):
    encoded = urllib.parse.quote(name)
    url = f"https://searchapi.eastmoney.com/api/suggest/get?input={encoded}&type=14&count=1"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())
    items = data.get("QuotationCodeTable", {}).get("Data", [])
    if items:
        return items[0]["Code"], items[0]["Name"]
    return None, None
```

**URL 编码注意**：
- 中文必须用 `urllib.parse.quote()` 编码
- 不要手动拼接中文字符到 URL 中——会导致 400 错误

## 验证代码准确性

查询到代码后，建议用腾讯行情 API 二次验证：
```bash
curl -s "https://qt.gtimg.cn/q=sz301061" | iconv -f gbk -t utf-8
```
