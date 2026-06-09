---
name: qing-learning-ingestion
description: |
  完整 ingestion 管线：raw → claims → wiki → index → commit。
  配合 qing-learning-claim（C2 编排写 claim）和 qing-learning-sync（知识库同步）使用。
---

# qing-learning-ingestion

## 前置依赖

此 skill 不直接包含写 claim 指令。写 claim 请加载 `qing-learning-claim` sub-skill + 运行编排管线。

## 完整工作流程

### Step 0: 确认 raw 未处理

```bash
# 检查 claims 和 wiki 是否已有对应内容
ls knowledge/claims/claim-YYYYMMDD-*.yaml 2>/dev/null
ls knowledge/wiki/每日复盘/YYYY-MM-DD.md 2>/dev/null
```

### Step 1: 写 Claim（走编排管线）

```bash
python scripts/extract_claims_pipeline.py start --raw sources/raw/财经/文件名.md
# → 按提示逐步完成 Step 1→Gate 1→Step 2→Gate 2→Step 3→Gate 3→Step 4
```

### Step 2: 移动 YAML 到正式目录

编排管线输出在 `temp/claims/<session_id>/step3_yaml/`。确认无误后：

```bash
# 检查目标编号是否被占用
ls knowledge/claims/claim-YYYYMMDD-*.yaml 2>/dev/null | tail -3
# 手动复制到正式目录，用正确的编号
cp temp/claims/<session_id>/step3_yaml/claim-*.yaml knowledge/claims/claim-YYYYMMDD-NNN.yaml
```

### Step 3: 更新关联 wiki

- 每日复盘：`knowledge/wiki/每日复盘/YYYY-MM-DD.md`
- 专题 wiki（如端侧AI、商业航天）：`knowledge/wiki/市场分析/主题名.md`

### Step 4: 更新三个索引文件

```bash
# ⚠️ 缺一不可
knowledge/claims/index.md
knowledge/wiki/index.md
knowledge/wiki/log.md
```

### Step 5: 提交

```bash
git add sources/raw/ knowledge/claims/ knowledge/wiki/
git commit -m "feat: ..."
```

## 关键坑

1. **同日期多 raw 的编号冲突**：写入前 `ls knowledge/claims/claim-YYYYMMDD-*.yaml` 检查，用递增编号
2. **同日期 wiki 覆盖**：写入每日复盘前 `read_file` 检查是否存在，合并而非覆盖
3. **最终修改 raw 的 ingest_status**：完成上述流程后，改 raw frontmatter `ingest_status: pending` → `ingest_status: processed`

## 参考文件

| 场景 | 参考文件 |
|------|---------|
| 图片转 raw | `references/image-to-raw-workflow.md` |
| 录音错别字修正 | `references/recording-transcript-correction.md` |
| B站文章提取 | `references/bilibili-article-content-extraction.md` |
| 混合内容（轨道A+轨道B） | `references/mixed-content-ingestion.md` |
| 用户手动录入 | 本 skill SKILL.md §「手动录入流程」 |
