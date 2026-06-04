# Image-to-Raw 文档整理工作流

> 将用户提供的图片（截图、Snipaste 等）整理为 qing-learning raw 文档的标准流程。

## 适用场景

- 用户发送多张图片，要求"整理成 raw 文档"
- 图片内容为博主复盘、早盘、午盘、研报等投资分析文字
- 图片来源：手机截图、Snipaste、微信转发等

## 工具链

| 工具 | 用途 | 优先级 |
|------|------|--------|
| `rapidocr_onnxruntime` | OCR 中文识别 | 首选（已安装） |
| `pytesseract` + `chi_sim` | OCR 中文识别 | fallback |
| PIL `Image.resize(2x)` | 放大图片提升 OCR 准确率 | 必做 |
| `--psm 6` | 假设统一文本块的页面分析模式 | 推荐 |
| 多区域裁剪 | 对长图分段 OCR 减少识别错误 | 长图必做 |

## 执行流程

### Step 1: 获取图片路径

图片缓存在 `/home/ubuntu/.hermes/image_cache/` 目录下，文件名如 `img_xxxx.jpg`。

### Step 2: OCR 识别

**首选：RapidOCR（已安装，中文识别更准）**
```python
from rapidocr_onnxruntime import RapidOCR
from PIL import Image

ocr = RapidOCR()
result, elapse = ocr('/home/ubuntu/.hermes/image_cache/img_xxxx.jpg')
for line in result:
    print(line[1])
```

**Fallback：pytesseract**
```python
from PIL import Image
import pytesseract

img = Image.open('/home/ubuntu/.hermes/image_cache/img_xxxx.jpg')
img2 = img.resize((img.width*2, img.height*2), Image.LANCZOS)
text = pytesseract.image_to_string(img2, lang='chi_sim+eng', config='--psm 6')
print(text)
```

**长图处理**：对高度 > 1000px 的图片，按上/中/下三段分别裁剪后 OCR：
```python
w, h = img.size
for i, y1 in enumerate([0, h//3, 2*h//3]):
    y2 = min(y1 + h//3 + 100, h)
    crop = img.crop((0, y1, w, y2))
    # ... resize + OCR
```

### Step 3: 检查图片重叠（多张图片时必做）

当用户提供多张图片时，必须主动检查内容是否重叠：

1. **比较章节标题**：如"四、板块策略"同时出现在两张图片中
2. **比较段落内容**：相同或高度相似的段落（如"AI方向：两天反弹后..."）
3. **判定重叠**：若发现重叠，保留更完整的版本，删除重复部分
4. **常见重叠场景**：
   - 长截图分页（上一张底部 = 下一张顶部）
   - 同一动态的多张图片
   - 用户重复发送

### Step 4: 日期推断（截图无日期标注时）

截图通常无日期标注，需通过以下方式推断：

1. **内容时间线索**：
   - "顶部结构第N天" → 与已有raw对比（昨天第15天→今天第16天）
   - "调整第N天" → 同上
   - "昨天创业板指冲高近4%" → 昨天发生过的事
2. **与已有raw对比**：检查 `sources/raw/财经/` 中最近日期的内容
3. **系统当前日期**：作为fallback
4. **标注要求**：推断出的日期必须在frontmatter中标注，并在正文中说明推断依据

### Step 5: 人工校对与补全

OCR 常见错误类型：
- 形近字误识：`般`→`股`，`焉`→`涨`，`侗`→`偏`，`倡`→`但`
- 标点丢失：中文引号 `""` 常被识别为乱码或缺失
- 表格错位：多列表格可能识别为单列
- 专有名词错误：`AIPC`→`APC`，`MLCC`→`WMLCC`

**校对策略**：
1. 通读 OCR 结果，标记明显不通顺的句子
2. 结合投资领域常识推断原词（如"AlPC"不会写成"APC"）
3. 对表格内容，参考图片结构手动重建表格
4. 对专有名词（股票代码、公司名、技术术语），用 grep 搜索项目已有文档交叉验证

### Step 6: 按 raw 格式规范化

1. **命名规则**：`类型：YY-MM-DD：简短描述.md`
   - 复盘 → `复盘：26-06-01：...`
   - 早盘 → `早盘：26-06-01：...`
   - 午盘 → `午盘：26-06-01：...`
2. **Frontmatter**：
   ```yaml
   ---
   date: 2026-06-04
   source_type: 早盘
   source_author: 青枫浦上Q
   source_url: ""
   ingest_status: pending
   ---
   ```
3. **结构化正文**：
   - 一级标题 `# 日期 类型`
   - 二级标题 `## 一、盘面定调` 等
   - 原文引用用 `> ` 块引用
   - 表格用标准 markdown 表格
   - 重点加粗 `**文字**`

### Step 7: 保存与验证

1. 写入 `sources/raw/财经/`
2. `ls -la` 确认文件存在
3. 快速通读检查格式一致性
4. **检查是否已存在同名/同内容文件**：写入前检查 `sources/raw/财经/` 和 `sources/original/bilibili/` 中是否已有相同内容（通过 `dynamic_id` 或独特短语匹配），避免重复创建
5. **更新 sources/processed-log.md**（可选）：若用户要求"学习"而非仅"整理"，将 raw 路径写入 processed-log，标记为待学习状态

## 常见陷阱

1. **OCR 漏识别**：图片底部/边缘的文字可能被裁剪遗漏，需分段 OCR 后拼接
2. **过度依赖 OCR**：不要直接复制 OCR 结果而不校对，专有名词和数字必须人工确认
3. **格式丢失**：OCR 不保留 markdown 格式（如表格、加粗），需手动重建
4. **图片顺序错乱**：多张图片时需确认顺序（通常按发送顺序），避免内容拼接错误
5. **重复内容**：多张图片可能有重叠内容（如上一张的底部和下一张的顶部），去重后整合
6. **重叠内容检测遗漏**：未主动检查多张图片的重叠，导致raw文档中出现重复段落
7. **日期推断错误**：未与已有raw对比，导致日期标注错误（如把"第16天"的内容标成"第15天"）

## 与 qing-learning 流程的衔接

图片整理为 raw 后，走标准 ingestion 流程：
1. 抽取 claims
2. 更新 wiki
3. 更新 index
4. Git 提交

但用户仅要求"整理成 raw 文档"时，**只做 raw 整理，不自动走 claims/wiki 流程**，等待用户后续指令。
