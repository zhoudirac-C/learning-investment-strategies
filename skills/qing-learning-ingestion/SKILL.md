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

# 检查原始文件是否已处理（sources/original/bilibili/ 目录下）
head -5 sources/original/bilibili/*.md 2>/dev/null | grep "unprocessed: true"
```

### Step 0.5: 将原始文件复制到 raw 目录

B站文件从 `sources/original/bilibili/` 获取，编排管线需要文件在 `sources/raw/财经/`：

```bash
# 找到待处理的原始文件
grep -l "unprocessed: true" sources/original/bilibili/*.md

# 复制到 raw 目录（文件名简短化，去掉特殊字符）
cp "sources/original/bilibili/原始文件名.md" "sources/raw/财经/YYYY-MM-DD-类别-简短描述.md"
```

**文件名规范**：去掉长中文描述中的特殊字符（如 `、` `）` `（` 等），用中划线分隔，保持日期+类别前缀。

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
3. **在原始文件标记已处理**：完成上述流程后，改原始文件 frontmatter `unprocessed: true` → `unprocessed: false`
4. **Pipeline done 清理失败**：`extract_claims_pipeline.py done` 检测到 temp 目录中尚有 YAML 会报错。如果已手动复制 YAML 到正式目录，直接 `rm -rf temp/claims/<session_id>` 手动清理即可
5. **缓存门禁结果阻塞重跑**：修改 step 产物（如 step2_enriched.json）后必须删除对应 `gateN_result.json` 缓存文件，否则 `continue` 读到旧缓存不会验证你的改动

## 参考文件

| 场景 | 参考文件 |
|------|---------|
| 图片转 raw | `references/image-to-raw-workflow.md` |
| 录音错别字修正 | `references/recording-transcript-correction.md` |
| B站文章提取 | `references/bilibili-article-content-extraction.md` |
| 混合内容（轨道A+轨道B） | `references/mixed-content-ingestion.md` |
| 用户手动录入 | 本 skill SKILL.md §「手动录入流程」 |
