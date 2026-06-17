# Bilibili 动态通知脚本维护指南

> 记录 `bilibili_notify.py` 及相关脚本的常见问题、修复方案和部署注意事项。

---

## 脚本位置与同步

| 位置 | 用途 | 同步要求 |
|------|------|---------|
| `~/learning-investment-strategies/scripts/bilibili_notify.py` | 项目源码 | 最新版本 |
| `~/.hermes/scripts/bilibili_notify.py` | cron 任务执行 | 必须与项目源码同步 |
| `~/.hermes/scripts/fetch_bilibili_up_v2.py` | cron 依赖库 | 必须与项目源码同步 |
| `~/.hermes/scripts/run_bilibili_notify.sh` | cron wrapper | 检查环境变量设置 |

**关键纪律**：修改项目目录下的脚本后，必须同步到 `~/.hermes/scripts/`，否则 cron 任务运行的是旧版本。

```bash
# 同步命令
cp ~/learning-investment-strategies/scripts/bilibili_notify.py ~/.hermes/scripts/
cp ~/learning-investment-strategies/scripts/fetch_bilibili_up_v2.py ~/.hermes/scripts/
```

---

## 已知问题与修复

### 问题1：函数名不匹配导致导入失败

**症状**：`ImportError: cannot import name 'fetch_top_comment'`

**根因**：`bilibili_notify.py` 导入 `fetch_top_comment`，但 `fetch_bilibili_up_v2.py` 中实际叫 `fetch_up_comment`。

**修复**：统一使用 `fetch_up_comment`（验证用户名的版本）。

```python
# bilibili_notify.py
from fetch_bilibili_up_v2 import (
    # ...
    fetch_up_comment,  # 不是 fetch_top_comment
    # ...
)

# 调用处
top_comment = fetch_up_comment(dynamic_id, sessdata)
```

### 问题2：专栏动态无内容

**症状**：提醒显示 "原文：（无文字内容）"

**根因**：`extract_text_from_dynamic` 只处理了 `opus`/`archive` 类型，没处理 `article`（专栏）。

**修复**：增加 `article` 类型支持。

```python
article = major.get("article") if major else None
if article and isinstance(article, dict):
    parts = []
    title = article.get("title", "")
    if title:
        parts.append(title)
    desc_text = article.get("desc", "")
    if desc_text and desc_text != "请将App客户端升级至最新版本后观看":
        parts.append(desc_text)
    return "\n".join(parts) or "（专栏文章，请访问原页面查看全文）"
```

### 问题3：cron 任务无 cookie

**症状**：`ERROR: 需要 BILIBILI_SESSDATA 环境变量`

**根因**：`bilibili_notify.py` 只从环境变量读取 SESSDATA，但 cron 任务没有设置该环境变量。

**修复**：增加从文件读取逻辑。

```python
sessdata = os.environ.get("BILIBILI_SESSDATA", "")

# 优先从文件读取 SESSDATA（二维码登录保存的）
sessdata_file = Path.home() / ".hermes" / "bilibili_sessdata.txt"
if not sessdata and sessdata_file.exists():
    sessdata = sessdata_file.read_text(encoding="utf-8").strip()
    if sessdata:
        print("INFO: 从文件读取 SESSDATA", file=sys.stderr)

if not sessdata:
    print("ERROR: 需要 BILIBILI_SESSDATA 环境变量", file=sys.stderr)
    return 1
```

### 问题4：旧版本脚本残留

**症状**：评论提取错误（抓到其他用户的热评）、函数行为不一致。

**根因**：`~/.hermes/scripts/` 下残留旧版 `fetch_bilibili_up_v2.py`，与项目目录下的新版行为不同。

**修复**：删除旧版，统一使用项目目录下的版本。

```bash
# 检查是否有旧版
ls ~/.hermes/scripts/fetch_bilibili_up_v2.py

# 删除旧版（如果存在且与项目版本不同）
rm ~/.hermes/scripts/fetch_bilibili_up_v2.py

# 复制新版
cp ~/learning-investment-strategies/scripts/fetch_bilibili_up_v2.py ~/.hermes/scripts/
```

---

## Cookie 管理

### 获取方式

1. **二维码登录**：运行 `scripts/bilibili_qr_login.py`，扫码后 cookie 保存到 `~/.hermes/bilibili_sessdata.txt`
2. **手动提取**：从浏览器开发者工具复制 SESSDATA，写入文件

### 验证有效性

```bash
python3 -c "
import urllib.request, json
sessdata = open('/home/ubuntu/.hermes/bilibili_sessdata.txt').read().strip()
url = 'https://api.bilibili.com/x/web-interface/nav'
req = urllib.request.Request(url, headers={
    'User-Agent': 'Mozilla/5.0',
    'Cookie': f'SESSDATA={sessdata}',
})
with urllib.request.urlopen(req, timeout=10) as resp:
    data = json.loads(resp.read().decode())
    print('isLogin:', data.get('data', {}).get('isLogin'))
    print('message:', data.get('message'))
"
```

### 过期处理

Cookie 有效期通常为 1-2 个月。过期后：
1. 重新运行二维码登录脚本
2. 或手动更新 `~/.hermes/bilibili_sessdata.txt`

---

## 提醒内容格式

### 当前格式（完整原文）

```
📢 **青枫浦上Q 新动态**

⏰ 2026年06月03日 23:02
🔗 https://www.bilibili.com/opus/...

**原文：**
[完整原文内容，无截断]

**图片内容：**
[OCR 结果，无截断]

**置顶评论：**
[UP主评论，无截断]
```

### 历史格式（已废弃）

旧版本有截断：原文前200字、OCR前300字、评论前200字，带 "..." 截断标记。

---

## 验证清单

修改脚本后必须执行：

- [ ] 项目目录脚本与 `~/.hermes/scripts/` 同步
- [ ] `fetch_bilibili_up_v2.py` 函数名一致（`fetch_up_comment`）
- [ ] Cookie 文件存在且有效
- [ ] 测试运行：`bash ~/.hermes/scripts/run_bilibili_notify.sh`
- [ ] 检查输出格式（无截断、无 "..."）
- [ ] 专栏类型动态能正确提取标题

---

## 相关文件

- `scripts/bilibili_notify.py` — 主通知脚本
- `scripts/fetch_bilibili_up_v2.py` — B站API封装
- `scripts/bilibili_qr_login.py` — 二维码登录
- `~/.hermes/bilibili_sessdata.txt` — Cookie 存储
- `~/.hermes/bilibili_up_state.json` — 已处理动态ID记录
