# B站 QR 登录 API 格式变更记录

## 背景

2026年7月28日，B站 QR 登录 API（`/x/passport-login/web/qrcode/poll`）返回格式发生变更。

## 变更

### 旧格式（2026年7月前）

```json
{
  "code": 0,
  "data": {
    "code": 0,
    "cookie_info": {
      "cookies": [
        {"name": "SESSDATA", "value": "xxx,xxx,xxx"},
        {"name": "DedeUserID", "value": "xxx"},
        ...
      ]
    }
  }
}
```

### 新格式（2026年7月起）

```json
{
  "code": 0,
  "data": {
    "url": "https://passport.biligame.com/x/passport-login/web/crossDomain?DedeUserID=xxx&SESSDATA=xxx,xxx,xxx&bili_jct=xxx&gourl=...",
    "code": 0,
    "message": ""
  }
}
```

- **`cookie_info.cookies` 数组消失**，SESSDATA 不再以 cookie 数组形式返回
- SESSDATA 改为嵌入在 `data.url` 的 query 参数中（redirect URL）
- `data.url` 是一个指向 `passport.biligame.com` 的 crossDomain 跳转链接

## 提取方法

```python
import urllib.parse

url = api_response["data"]["url"]
parsed = urllib.parse.urlparse(url)
params = urllib.parse.parse_qs(parsed.query)
sessdata = params.get("SESSDATA", [None])[0]
```

## 兼容处理

提取 SESSDATA 时应同时兼容两种格式：

1. 优先尝试 `cookie_info.cookies`（旧格式）
2. 回退到 `data.url` query 参数（新格式）
3. 两种都失败时打印完整 API 响应到 stderr 用于调试

## 验证

新 SESSDATA 保存后，通过 `/x/web-interface/nav` API 验证：

```python
req = urllib.request.Request(
    "https://api.bilibili.com/x/web-interface/nav",
    headers={"User-Agent": "...", "Cookie": f"SESSDATA={sessdata}"}
)
nav = json.loads(urllib.request.urlopen(req).read())
uname = nav["data"]["uname"]  # 应显示登录用户名
```
