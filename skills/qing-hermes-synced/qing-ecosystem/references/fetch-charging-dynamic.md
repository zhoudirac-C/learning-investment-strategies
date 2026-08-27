# 手动拉取充电专属动态内容

## 背景

B站充电专属（`is_only_fans: true`）的图片/截图动态在离线抓取时只有元数据没有文字内容（`（无文字内容）`），需要通过 API 接口 + Cookie SESSDATA 拉取详情，再 OCR 图片提取文字。

## 前置条件

- SESSDATA 文件存在 `~/.hermes/bilibili_sessdata.txt`（充电会员有效）
- 目标 dynamic_id（从 raw 文件名或 URL 中提取）

## 工作流

### Step 1: API 拉取动态详情

```bash
SESSDATA=$(cat ~/.hermes/bilibili_sessdata.txt)
DYNAMIC_ID="1230001616247062569"  # 替换为目标 ID

curl -s "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail?id=$DYNAMIC_ID" \
  -H 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' \
  -H 'Referer: https://t.bilibili.com/' \
  -H "Cookie: buvid3=<REDACTED>infoc; SESSDATA=$SESSDATA; b_nut=1768824333; _uuid=<REDACTED>infoc;" \
  --max-time 15
```

也可以用 Python 调用 `fetch_bilibili_up_v2.py` 中的 `fetch_dynamic_detail()` 函数。

### Step 2: 提取图片 URL

响应中的字段路径：

```
data.item.modules.module_dynamic.major.draw.items[].src
```

图片类型有 `draw`（多图）、`archive`（视频）、`article`（专栏）、`opus`（富文本）等。

对 draw 类型：
```python
major = item["modules"]["module_dynamic"]["major"]
if "draw" in major:
    items = major["draw"]["items"]  # 列表，每个有 src/width/height
    for img in items:
        print(img["src"])
```

### Step 3: 下载 + OCR

**首选**：脚本内置的 `ocr_image_from_url()`（基于 RapidOCR）

如果超时/失败，**改用 Tesseract**：

```bash
# 下载图片
curl -s -o /tmp/ocr_img.jpg "http://i0.hdslb.com/bfs/new_dyn/xxx.jpg" --max-time 15

# OCR（中文）
tesseract /tmp/ocr_img.jpg /tmp/ocr_out -l chi_sim+eng --psm 6
cat /tmp/ocr_out.txt
```

对于中文截图，`chi_sim` 效果好于 `chi_sim+eng`。对于复杂截图（小字、图表、重叠文字），效果有限，接受即可。

### Step 4: 更新 raw 文件

将 OCR 提取的文字写入 raw 文件中，替换 `（无文字内容）`：

```
## OCR 提取

图片1：转发推文截图
---
来源：@xxx
时间：7月26日 1:02上午

正文：
[OCR 提取的文字内容]

图片2：截图（内容暂无法有效OCR）
```

### Step 5: 判断是否需要提取 claim

| 内容类型 | 是否提取 | 理由 |
|---------|---------|------|
| UP 原创分析（早盘/盘中/复盘观点） | ✅ 提取 | 核心知识 |
| UP 自用的产业链/标的跟踪记录 | ✅ 提取 | 框架性信息 |
| 转发/截图他人帖子（非UP分析） | ❌ 跳过 | 非原创，价值低 |
| 普通段子/闲聊 | ❌ 跳过 | 无分析价值 |
| 图表截图（无文字说明） | ❌ 跳过 | 无法有效提取 |

判断依据：
- UP 发帖时间在交易时段 → 大概率是盘中观点 → 提取
- 内容含"转发""来源：@"等标记 → 大概率是 repost → 跳过
- 内容以截图为主且 OCR 结果模糊 → 与用户确认后再决定

## 常用 Stock Codes 查询

```bash
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=公司名&type=14&count=1" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d['QuotationCodeTable']['Data'][0]['Code'], d['QuotationCodeTable']['Data'][0]['SecurityTypeName'])"
```

## 坑点

1. **OCR 超时**：RapidOCR 首次加载可能下载模型（>60s），如果 `uv run` 超时，先用 tesseract 兜底
2. **图片2难以OCR**：图表/复杂截图用 tesseract 可能完全读不出，标注"暂无法有效OCR"即可，不阻塞流程
3. **`__pycache__` 干扰**：`uv run` 可能因缓存冲突超时，检查 `.venv` 环境或直接用系统 python3
4. **Cookie 过期**：如果 API 返回 `is_only_fans: true` + 内容仍 blocked，说明 SESSDATA 已过期，需更新
