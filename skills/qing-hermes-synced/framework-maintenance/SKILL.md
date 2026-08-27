---
name: framework-maintenance
description: |
  方法论复盘 → 推理框架维护。检查 reasoning-patterns.yaml 是否有需要更新的方法论
  （新 pattern 提名 / examples 批量提取 / 框架结构演进），以及核对 raw 文件是否已
  提取过 claim。触发词：查看 framework 是否有需要更新、方法论复盘、框架对比、
  pattern 提名、推理模式更新、raw 文件提取核对、extract_reasoning_patterns。
---

# framework-maintenance

推理框架（`framework/reasoning-patterns.yaml`）的维护方法论。与 `qing-learning-review`
（项目内 skills/，会话中可写、curator 只读）互补：本 skill 沉淀可复用的流程与坑位。

## 核心认知（2026-08-15 实测）

1. **框架数不是固定的**：reasoning-patterns.yaml 现为 **11 个框架**（position_by_cycle 是
   提案制新增的第 11 个）——不要假设固定 10 个。框架演进路径 = 提案制；批量提取只填充 examples。
2. **两条更新路径互补**：
   - 批量提取 `extract_reasoning_patterns.py --incremental`：新 raw 文件的推理链 →
     追加进现有框架的 examples（动态读框架列表，不硬编码）
   - 提案制 `framework/proposals/`：现有框架装不下的新推理模式 → 提名 → ≥4 周窗口验证 →
     人审 → 入库。**others 归入 = 框架改造信号**，应走提案制。
3. **proposals 不是 skill 触发的**：是归因流程产物（`shadow/attribute.py` 的 ATTR_PROMPT
   调 LLM 归因 → proposals[] 落盘），人工触发（对照 UP 时）。

## 方法论复盘-框架对比流程（14 天窗口实测）

完整实操见 `references/methodology-review-framework-comparison.md`，要点：

1. claims 统计：execute_code 解析 `knowledge/claims/claim-*.yaml`（source_date >= 窗口），
   按日/claim_type/confidence 分布；methodology 类是框架对比重点。
2. 读框架现状：pattern_id/name/description/examples key_themes。
3. 交叉对比：methodology claims 按主题集群分组 → 关键词搜 yaml 全文判断覆盖度。
   ⚠️ **关键词噪声**：data_requirements/trigger 里的词（如「晋级率」「外盘」）不代表
   推理步骤被覆盖，看上下文是数据通道还是 steps[].action。
4. 高频方法论识别：统计集群命中 claim 数——高频（如连板梯队定量 26 次、断板性质二分法
   16 次）却没进 framework = 盲判缺推理能力的根因，必提名。
5. 写提案（现有 .md 格式：frontmatter + 模式内容/触发与动作/证据/配套数据通道），
   转正门槛：≥4 周窗口 + ≥2 种市场阶段 + 证据（日期/regime/quote）。
6. 报告落 `reports/methodology-review-YYYYMMDD.md` + git 提交。

## raw 提取覆盖核对（⚠️ 三重验证，用户纠正过「不可能没提取」）

判断 raw/财经/ 文件是否已提取过 claim，**不能只靠文件名匹配**：

| 验证法 | 说明 |
|--------|------|
| ① source_path 精确匹配 | claims source_path 有 **4 种目录**（chanlun/raw/original/home），只匹配 '/raw/' 会漏 |
| ② original 目录 dynamic_id 关联 | raw 副本与 `sources/original/bilibili/` 用 dynamic_id 关联；original 被引用 = 已提取 |
| ③ **Qdrant 语义搜索（最可靠）** | 取文件关键句搜 claims 库，看有无对应观点 |

关键事实：daily claim 提取只覆盖新内容，历史文件（1-7 月）可能未回填（original 342 只引用
115 个=34%）；`extract_reasoning_patterns.py` 的 state（processed_files）≠ claims 覆盖；
图片动态（unprocessed: true）是空壳（正文在 OCR），raw 副本无提取价值。

## 脚本修复要点（2026-08-15）

`extract_reasoning_patterns.py`：框架列表**从 yaml 动态读**（`load_frameworks()`，失败用
`_FALLBACK_FRAMEWORKS` 兜底），EXTRACTION_PROMPT 动态拼装（`build_extraction_prompt`）；
matched_framework 归不进去落 others 时打印「新框架信号」提示（引导提案制）。修改后验证：
`load_frameworks()` 返回 11 个、prompt 含新框架 id、`--dry-run` 正常。
