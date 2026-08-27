# 方法论复盘：框架对比实操流程（2026-08-15 实测，窗口 14 天）

用户在「qing review」时要求「查看 framework 是否有需要更新的」——按此流程跑，
产出 reports/methodology-review-YYYYMMDD.md + proposals 提名。

## 1. Claims 统计（execute_code 解析，勿用 grep）

```python
import yaml, glob, collections
claims = []
for f in glob.glob('knowledge/claims/claim-*.yaml'):
    data = yaml.safe_load(open(f, encoding='utf-8'))
    for c in (data.get('claims') or []):
        if str(c.get('source_date','')) >= '2026-08-01':  # 窗口起点
            claims.append(c)
# 按日 / claim_type / confidence 分布
```
注意：claim 文件名 `claim-YYYYMMDD-NNN.yaml`，source_date 是 'YYYY-MM-DD'（带引号）。

## 2. 提取 methodology claims（框架对比重点）

`claim_type == 'methodology'` 是框架对比的核心；其余类型（sector-theme/market-cycle/
operation 等）做主题统计即可。

## 3. 读框架现状

```python
data = yaml.safe_load(open('framework/reasoning-patterns.yaml', encoding='utf-8'))
for p in data['patterns']:
    # pattern_id / name / description / examples[].key_themes
```
⚠️ **框架数是会变的**：2026-08-15 是 11 个（position_by_cycle 是提案制新增的第 11 个），
不要假设固定 10 个。

## 4. 交叉对比（找未收录方法论）

- 把 methodology claims 按主题集群分组（如「外盘只定价开盘」「连板梯队定量」「断板性质」）
- 用关键词在 yaml **全文**搜索判断覆盖度
- ⚠️ **关键词噪声**：yaml 的 data_requirements/trigger 里出现的词（如「晋级率」「外盘」）
  不代表推理步骤被覆盖——需看上下文是数据通道还是 steps[].action。
- 核对 proposals 状态：`framework/proposals/*.md` 的 frontmatter `status:` 字段
  （proposed=待窗口验证 / done=已实施）

## 5. 高频方法论识别（重大发现来源）

统计每个主题集群命中的 methodology claim 数——高频出现（如连板梯队定量 26 次、
断板性质二分法 16 次）却没进 framework，是盲判缺推理能力的根因，必提名。

## 6. 写提案（现有格式，frontmatter + 分节）

```markdown
---
date: YYYY-MM-DD
type: pattern-nomination
status: proposed（待窗口验证：需积累 ≥4 周跨 regime 命中记录后转正）
source: reports/methodology-review-YYYYMMDD.md + knowledge/claims/claim-xxx
---
# 模式提名：<名称>
## 模式内容 / ## 触发与动作 / ## 证据（跨 regime）/ ## 配套数据通道
```
转正门槛（qing-learning-review Step 5）：≥4 周窗口 + ≥2 种市场阶段 + 每次出现的
日期/regime/quote 证据。

## 7. raw 提取覆盖核对（⚠️ 三重验证，2026-08-15 用户纠正「不可能没提取」）

判断 raw/财经/ 文件是否已提取过 claim，**不能只靠文件名匹配**：

| 验证法 | 说明 |
|--------|------|
| ① source_path 精确匹配 | claims 的 source_path 有 **4 种目录**：chanlun / raw / original / home——只匹配 '/raw/' 会漏 |
| ② original 目录 dynamic_id 关联 | raw 副本与 `sources/original/bilibili/` 通过 dynamic_id 关联；original 被 claims 引用 = 内容已提取 |
| ③ **Qdrant 语义搜索（最可靠）** | 取文件关键句搜 claims 库（mcp__qdrant__search_claims），看有无对应观点 |

关键事实（2026-08-15 实测）：
- **daily claim 提取只覆盖新内容**，历史文件（1-7 月）可能未回填：original 342 个只被引用 115 个（34%）
- `extract_reasoning_patterns.py` 的 state（processed_files 200）≠ claims 覆盖（360 引用）
- **图片动态（unprocessed: true）是空壳**：raw 副本正文为空（内容在图片 OCR），
  这类没有提取价值；`extract_reasoning_patterns.py` 的首 500 字符无分析关键词过滤会 skip
- 乱码检测：UTF-8 解码失败或 \ufffd 替换字符 >50 才算乱码；2026-08-15 全量 550 个文件 0 乱码
- `extract_reasoning_patterns.py --dry-run` 的 "candidates" 已是未标记候选（不是总数减已处理），
  别把输出理解错

## 8. 报告 + 提交

- 报告落 `reports/methodology-review-YYYYMMDD.md`，结论前置（3-5 条）+ 量化 + 区分事实/判断
- `git add` 报告 + 新提案后 commit
