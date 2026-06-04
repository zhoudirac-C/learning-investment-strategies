# B站专栏文章正文提取

## 问题

B站 **动态 API**（`/x/polymer/web-dynamic/v1/`）对专栏文章（`DYNAMIC_TYPE_ARTICLE`）不返回正文——即使调用了 `detail` API，`modules.module_dynamic.major.article` 也只有 `title`、`desc`、`covers`、`id`、`jump_url`、`label` 字段。

`desc` 通常为无用的 `"请将App客户端升级至最新版本后观看"`。

B站 **文章 API**（`/x/article/viewinfo?id={id}`）对**充电专属**（`is_only_fans: true`）专栏返回 `-404 "啥都木有"`。

## 解决方案

正文藏在 B站 **read 页面** 的 `window.__INITIAL_STATE__` JSON 中。

### 端点

```
GET https://www.bilibili.com/read/cv{article_id}
```

其中 `article_id` 从动态数据中提取：

```python
modules = item.get("modules", {})
dyn_mod = modules.get("module_dynamic", {})
major = dyn_mod.get("major", {})
article = major.get("article", {}) or {}
article_id = article.get("id", "")  # e.g. "50080244"
```

### 提取正文

```python
import re, json, urllib.request

req = urllib.request.Request(f"https://www.bilibili.com/read/cv{article_id}")
req.add_header("User-Agent", "Mozilla/5.0 ...")
req.add_header("Cookie", f"SESSDATA={sessdata}")  # 必需！无 cookie 会返回充电专属墙
req.add_header("Referer", "https://www.bilibili.com/")

with urllib.request.urlopen(req, timeout=15) as resp:
    html = resp.read().decode("utf-8", errors="replace")

match = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?});", html, re.DOTALL)
data = json.loads(match.group(1))

modules = data.get("detail", {}).get("modules", [])
content_parts = []
for mod in modules:
    if not isinstance(mod, dict):
        continue
    para_container = mod.get("module_content", {})
    if not para_container:
        continue
    paragraphs = para_container.get("paragraphs", [])
    for para in paragraphs:
        nodes = para.get("text", {}).get("nodes", [])
        line_words = []
        for node in nodes:
            if node.get("type") == "TEXT_NODE_TYPE_WORD":
                w = node.get("word", {}).get("words", "")
                if w:
                    line_words.append(w)
        if line_words:
            content_parts.append("".join(line_words))

full_text = "\n\n".join(content_parts)
```

### 原理

B站 read 页面服务器端渲染时，将文章段落数据嵌入到 `window.__INITIAL_STATE__` 的 `detail.modules` 数组中。`MODULE_TYPE_TITLE`（索引0）是标题，`module_content` 模块（索引通常为2）包含所有段落。

段落结构：
```json
{
  "module_content": {
    "paragraphs": [
      {
        "text": {
          "nodes": [
            {
              "type": "TEXT_NODE_TYPE_WORD",
              "word": {"words": "一、表面修复，底层分歧"}
            }
          ]
        }
      }
    ]
  }
}
```

### 注意事项

1. **SESSDATA 必须有效**：无 cookie 或过期 SESSDATA 会导致页面返回充电专属墙而非文章内容。需确保 `sessdata` 是 UP主 充电用户的 cookie。
2. **标题已包含在 INITIAL_STATE**：`detail.modules[0].module_title.text` 即为文章标题，与动态列表中的 title 一致。
3. **段落分隔**：相邻段落用 `\n\n` 分隔，效果接近原文排版。
4. **图片不可空过**：此方法只能提取文字，无法获取文章内嵌图片。有图需求的充电专属文章仍需要 OCR 或浏览器截图。
5. **不依赖文章 API**：`/x/article/viewinfo` 返回 -404 时，此方法仍然可用。
6. **文章列表页 URL**：`https://www.bilibili.com/read/cv{article_id}` 而非 `https://www.bilibili.com/opus/{dynamic_id}`。
