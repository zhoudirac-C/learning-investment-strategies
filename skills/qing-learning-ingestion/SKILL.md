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

### Step 6: Methodology Check（方法论感知）

每轮 ingestion 完成后，检查本次新增的 claims 是否包含大盘分析方法论：

```bash
# 检查新 claims 中是否有 methodology 类型
grep -l "claim_type: methodology" knowledge/claims/claim-YYYYMMDD-*.yaml | while read f; do
  grep "timeframe: permanent" "$f" >/dev/null && echo "  → $f"
done
```

若检测到方法论 claims，输出提示：
```
本轮 ingestion 新增 X 条方法论 claims。建议运行「更新方法论」合并到 framework。
```

**⚠️ 此步骤不自动写 framework。** 必须等用户明确指令（"更新方法论"）后才执行合并。Agent 只做检测和提醒。

## 关键坑

1. **同日期多 raw 的编号冲突**：写入前 `ls knowledge/claims/claim-YYYYMMDD-*.yaml` 检查，用递增编号
2. **同日期 wiki 覆盖**：写入每日复盘前 `read_file` 检查是否存在，合并而非覆盖
3. **在原始文件标记已处理**：完成上述流程后，改原始文件 frontmatter `unprocessed: true` → `unprocessed: false`
4. **Pipeline done 清理失败**：`extract_claims_pipeline.py done` 检测到 temp 目录中尚有 YAML 会报错。分两种情况：
   - **已复制但未改文件名**：直接 `rm -rf temp/claims/<session_id>` 手动清理即可
   - **复制时改了文件名**（如 `claim-2026-06-12-output.yaml` → `claim-20260612-002.yaml`）：pipeline 按原始文件名查找，找不到也会报错。同样 `rm -rf temp/claims/<session_id>` 手动清理
5. **缓存门禁结果阻塞重跑**：修改 step 产物（如 step2_enriched.json）后必须删除对应 `gateN_result.json` 缓存文件，否则 `continue` 读到旧缓存不会验证你的改动
6. **低信息含量帖文跳过 claim 提取** — 不是所有 UP 动态都需要提取 claims。以下类型应直接标记 `unprocessed: false`，不入库：
   - **寓言/故事/段子**：纯比喻式表达，没有具体标的、板块、操作区间、止损/介入条件。例：UP 的「上帝为什么不救你」寓言
     - 注意：寓言不是机会信号而是风险警示。UP 在调整初期/市场乐观时发寓言→看空警示；在冰点期/恐慌时发寓言→心理按摩。核心信息在第一句，不在故事细节。
   - **心理按摩/行为偏差提醒**：吐槽空仓者心态、从众行为等，没有可验证的判断或可执行的交易决策
   - **仅附图无文字增量**：充电专属的图片动态，文字只是图片说明或重复已有观点
   
   **判断标准**：
   - 是否有可查询的 structured 信息（具体标的、板块、价格）？→ ❌ 则跳过
   - 是否有可验证的判断（明天涨/跌、某个条件满足后买入）？→ ❌ 则跳过
   - 是否能驱动后续交易决策（止损/建仓/方向调整）？→ ❌ 则跳过
   - 是否有独立引用的价值（未来搜索时能找到的有用信息）？→ ❌ 则跳过
   
   这些帖文的正确处理方式是：读完、理解，然后不入库，直接标记已处理。

7. **UP高语境/隐喻式帖文的分析原则（2026-06-12 新增）**：
   UP有时会用寓言/故事/比喻来表达市场观点。处理这类帖文时：
   
   **核心原则：读字面，不创造**
   - 只提取原文明确说了什么——具体名词、动词、判断句
   - 不要给比喻元素分配映射关系（如木盆=初步信号，船=明确策略，直升机=具体标的）
   - 不要引申、不要创造UP没说过的逻辑链
   
   **操作方法**：
   1. 先摘出文字部分的直白观点（通常是第一段）：核心信息在开头，不在故事细节
   2. 寓言部分只保留不处理——它的作用是增强语气，不是提供可提取的信息
   3. 如果全文只有比喻没有直白观点，走低信息含量帖文跳过规则
   4. 如果用户指出理解错误，重读原文只关注字面意思，删除所有自己添加的映射

## 隔离区 claim 同步到主库（2026-10-29 新增）

当 watchlist 学派 UP 的 claim 需要迁入主库时（如用户指令"同步到主库"），按以下流程：

1. **检查编号冲突**：`ls knowledge/claims/claim-YYYYMMDD-*.yaml`，确认新编号不被占用。从该日期最大现有编号 + 1 开始递增。
2. **重新编号**：隔离区编号 `claim-YYYYMMDD-NNN-x`（带字母后缀）→ 主库编号 `claim-YYYYMMDD-NNN`（纯数字递增，无字母后缀）。
3. **单文件拆分**：隔离区 YAML 可能是列表结构（一个文件包含多条 claim），需拆分为主库单条 YAML 文件（每条 claim 一个文件，文件名 = id）。
4. **格式转换**：
   - 移除 `school`、`disagrees_with` 字段（watchlist 专用，主库不保留）。
   - `links` 改为列表形式（`links: []` 或 URL 列表），移除嵌套 dict `wiki_pages`/`methodology_pages`/`cases`。
   - `last_discovered` 确保为字符串格式（YAML 可能将 `2026-10-28` 解析为 date 对象，写回时需保持字符串，不要带引号）。
   - 确认 `stance`、`claim_type`、`timeframe`、`confidence`、`status` 等枚举值符合主库 Gate 1 约束（见 `qing-claim-gate-troubleshoot` 的 Gate 1 速查）。
5. **更新索引**：将新文件追加到 `knowledge/claims/index.md`，按日期+编号顺序插入。
6. **提交**：`git add knowledge/claims/ knowledge/claims/index.md` → commit → push。
   - 原文件保留：隔离区原文件 `archive/schools/watchlist/claims-quarantine.yaml` 不做删除，主库是增量写入。

## 参考文件

| 场景 | 参考文件 |
|------|---------|
| 图片转 raw | `references/image-to-raw-workflow.md` |
| 录音错别字修正 | `references/recording-transcript-correction.md` |
| B站文章提取 | `references/bilibili-article-content-extraction.md` |
| 混合内容（轨道A+轨道B） | `references/mixed-content-ingestion.md` |
| **大盘方法论批量提取** | `references/bulk-methodology-extraction-guide.md` |
| 用户手动录入 | 本 skill SKILL.md §「手动录入流程」 |
