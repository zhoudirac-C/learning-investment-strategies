# 图片转 raw 工作流（B站纯图片动态 OCR）

## 适用场景

B站充电专属图片动态（`DYNAMIC_TYPE_DRAW`）正文显示"（无文字内容）"、
或只有图片说明没有正文时，内容在图片里，需要 OCR 提取后才能走 claim 管线。

**2026-07-31 实战**：11:20 动态为纯图片（观察池截图），OCR 后提取出
浪潮软件(600756)/久其软件(002279) 两条 stock-view claims。

## 判断"无文字内容"是否值得 OCR

低信息含量帖文（无实质观点）跳过，不值得 OCR。有观察池/标的/价格/触发条件的
截图才值得。判断标准与 `qing-learning-ingestion` §6 相同。

## 工作流

### 1. 从原始文件提取真实图片 URL

`fetch_bilibili_up_v2.py` 保存的文件里嵌了完整 API 数据（`## 原始API数据` JSON）。
**注意过滤**：头像/装饰图（`bfs/face/`、`bfs/garb/`、`bfs/vip/`、`activity-plat/`）
不是动态内容图。真实动态图在 `bfs/new_dyn/` 路径下：

```bash
python3 -c "
import re
content = open('sources/original/bilibili/<文件>.md').read()
urls = re.findall(r'https?://[^\"\')\s]*bfs/new_dyn/[^\"\')\s]+', content)
for u in dict.fromkeys(urls): print(u)
"
```

（若 JSON 字段被截断，可直接用 `extract_pics_from_dynamic(item)` 从 API 列表响应拿，
参考 `scripts/fetch_bilibili_up_v2.py:512`。）

### 2. 安装 OCR 依赖（项目 venv）

```bash
cd ~/learning-investment-strategies && .venv/bin/pip install rapidocr_onnxruntime
```

脚本本身用的是 RapidOCR（`scripts/fetch_bilibili_up_v2.py:283 ocr_image()`），
安装后即可复用。注意脚本在**抓取时**默认 enable_ocr=True，但 OCR 依赖缺失时
静默返回空字符串——所以"无文字内容"≠ 没图，而是 OCR 没跑成功。

### 3. 下载 + 长图分块 OCR

长图（>2000px 高）必须分块，RapidOCR 一次性处理长图会丢字/报错：

```python
from rapidocr_onnxruntime import RapidOCR
from PIL import Image
import urllib.request

for url in image_urls:
    urllib.request.urlretrieve(url, '/tmp/bili_ocr/tmp.jpg')
    img = Image.open('/tmp/bili_ocr/tmp.jpg')
    w, h = img.size
    ocr = RapidOCR()
    texts = []
    for y in range(0, h, 2000):   # 每块最大 2000px 高
        chunk = img.crop((0, y, w, min(y + 2000, h)))
        result, _ = ocr(chunk)
        if result:
            for line in result:
                t = line[1] if isinstance(line[1], str) else (line[1][0] if len(line) > 1 else '')
                if t.strip():
                    texts.append(t)
    print('\n'.join(texts))
```

（完整封装见 `scripts/fetch_bilibili_up_v2.py` 的 `ocr_image()` / `ocr_image_from_url()`，
本项目环境已装 PIL。）

### 4. 回填原文 + 走正常管线

```bash
# 把 OCR 文本写回原始文件原文区（标注"图片内容 OCR 识别"）
# 然后 cp → sources/raw/财经/ → extract_claims_pipeline.py start
```

OCR 出的标的代码直接可信（截图内嵌），但**仓位/触发条件数字要保留原样**，
interpretation 里注明"观察池为盘后生成，触发条件是板块联动而非个股独立信号"。

## 坑

- OCR 文本有错别字是常态（手机截图+中文识别），提取 claim 时用语义理解，
  不要逐字复制进 evidence_quote——但**股票代码、价格数字必须逐字核对**
- 观察池截图可能混入无关 UI 文字（收益排名、按钮文案），提取时只取标的相关行
- `bfs/face/`、`bfs/garb/` 是头像和装扮图，不是动态内容，别下载浪费流量
