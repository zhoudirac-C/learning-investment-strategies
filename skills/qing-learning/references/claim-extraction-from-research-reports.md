# 从研报文档提取 Claims 的工作流

> 关联：`knowledge/claims/claim-20260604-007.yaml`（首次应用本模式的案例）
> 触发条件：UP 视频/复盘引用「翻动态里的研报图片」或 raw 文档包含机构标的汇总表

## 问题

UP 的某些视频（如 6/4 磨底期策略）包含从动态图片研报中汇总的标的清单。这些标的来自 UP 转发的机构研报，原始文件存储在 `sources/raw/财经/研报：*.md`。

如果只从视频 raw 文件提取 claims，会遇到两个问题：
1. **标的清单不被提取**：claim 提取侧重 UP 的判断/推理，标的行被视为附属数据，不会独立成 claim
2. **source_path 指向错误**：如果创建 claims，source_path 指向视频 raw 而非原始研报，Agent 检索时缺少来源追溯

## 解决方案

### Step 1: 识别需要研报提取的信号

当视频 raw 文件包含以下特征时，触发本流程：
- 正文有「把我动态里带图片的翻到 X 月份」类指示
- 有研报标的汇总表（如 6/4 视频第十一节）
- `key_topics` 包含多个非科技方向

### Step 2: 找到原始研报文件

```bash
ls sources/raw/财经/研报：* | head -20
```

原始研报文件命名格式：`研报：YY-MM-DD：标题.md`，包含完整的机构推荐逻辑、业绩数据、估值分析，远超视频汇总表中的一行摘要。

### Step 3: 按方向创建 claim

每个方向一条 claim，`source_path` 指向最主要的原始研报文件：

```yaml
claim_type: sector-theme
confidence: low  # 机构研报非 UP 独立判断
source_type: 机构研报（UP动态转发）
evidence_quote: 从原始研报提取的关键逻辑
interpretation: 标注主板/创业板/科创板可交易性
```

### Step 4: 约定

- **不要创建衍生研报文件**：不要从视频表格复制内容创建新的研报文件。原始 `sources/raw/财经/研报：*.md` 已存在且更完整
- **一个方向一条 claim**：不要 16 只储能标的拆 16 条，也不要所有方向合并为一条
- **related_stocks 只填主板可交易**：创业板/科创板/港股放在 statement 中，不在 links 中作为可操作标的
- **解释差异**：若 UP 视频中的评价（如「六氟优于锂矿」）比原始研报更强，在 interpretation 中标注
