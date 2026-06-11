---
name: qing-learning-claim
description: |
  Claim 编写与验证门禁。使用 C2 编排管线提取 claims，每步 Python 门禁强制校验。
  触发词：提取 claim、写 claim、学这篇、消化、ing
---

# qing-learning-claim

## 核心管线

写 claim 不走"纯 LLM → 提交"路径，而是走 **C2 编排管线**：

```
Step 1: Agent 读 raw → 写宽松 JSON → Gate 1 校验 18 字段
Step 2: Agent 读 JSON → 补股票代码 + related_stocks → Gate 2 校验代码/格式
Step 3: Python 自动格式化 → YAML → Gate 3 最终校验
Step 4: Agent 更新 wiki/index/commit
```

## 使用方法

### 启动新提取

```bash
python scripts/extract_claims_pipeline.py start --raw sources/raw/财经/文件名.md
```

输出是一个 JSON 指令，包含"下一步做什么"和"输出位置"。按提示执行。

### 继续流程

每完成一步后运行：

```bash
python scripts/extract_claims_pipeline.py continue
```

脚本自动运行对应门禁：
- 通过 → 输出下一步指令
- 失败 → 输出错误列表，退回修正

## 约束速查

### 18 个必需字段

| # | 字段 | 说明 |
|---|------|------|
| 1 | id | `claim-YYYYMMDD-NNN-x` 格式 |
| 2 | source_path | raw 文件路径 |
| 3 | source_date | YYYY-MM-DD |
| 4 | source_type | 专栏/视频/复盘/动态 |
| 5 | extracted_at | ISO 时间戳 |
| 6 | claim_type | market-cycle/sector-theme/stock-view/methodology/risk/technical-signal/technical-knowledge/macro/operation/catalyst/general |
| 7 | subject | 单一主题（无`/`、`、`、`+`） |
| 8 | timeframe | intraday/short-term/trend/industry/permanent |
| 9 | statement | 核心观点，包含公司名(6位代码) |
| 10 | evidence_quote | 原文引用 |
| 11 | interpretation | 解读分析 |
| 12 | confidence | high/medium/low |
| 13 | status | active/superseded/contradicted/expired/case-only |
| 14 | intensity | high/medium/low |
| 15 | supersedes | list[str] |
| 16 | contradicts | list[str] |
| 17 | links | {wiki_pages, methodology_pages, cases} |
| 18 | topic | 一句话主题 |

### related_stocks 格式

```yaml
# ✅ 正确（结构化对象，在 claim 顶级，不在 links 下）
related_stocks:
- code: 600118
  name: 中国卫星
  role: 卫星链龙头-主板可交易

# ❌ 旧格式（字符串，Agent 无法结构化检索）
related_stocks: [中国卫星(600118)]

# ❌ 错误（嵌套在 links 下，Agent 检索不到）
links:
  wiki_pages: []
  related_stocks: []  # ← 错误位置！
```

### 股票代码查询

```bash
# 东方财富搜索 API
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=公司名&type=14&count=1"
# 返回 JSON → QuotationCodeTable.Data[0].Code
```

### 自检清单（每步执行前打勾）

```
Step 1:
☐ 已逐段阅读全文，无遗漏
☐ 每条 claim 只有 1 个主题
☐ 18 个必需字段齐全

Step 2:
☐ statement 和 interpretation 中所有公司名已带 6 位代码
☐ related_stocks 已填结构化对象（无标的写 []）
☐ non-mainboard 已在 role 中标注不可交易
☐ tags 已补充（3-5 个）

Step 4:
☐ 已更新 wiki/index/log
☐ git commit 已推
```

## 已知坑点

### 1. Gate 结果缓存导致重跑卡在失败状态

Gate 1/2/3 的结果缓存（`gate1_result.json` / `gate2_result.json` / `gate3_result.json`）
在 `continue` 时作为「是否已验过」的判断依据存在。修改 step 产物后若缓存未清理，
pipeline 会跳过门禁重跑，继续输出 retry 指令。

**症状**：你修正了 step 文件（如 step2_enriched.json）中的错误（如补了股票代码），
但 `continue` 仍然输出与之前**完全相同的错误列表**。这不是你的修正无效——
而是 pipeline 读了缓存的 `gateN_result.json`，没看到你的改动。

**根因**（`extract_claims_pipeline.py:313`）：
```python
if step2_file.exists() and not (sess_dir / "gate2_result.json").exists():
```
pipeline 不比较时间戳——不知道 step 产物被编辑过。

**修复**：删除对应 gate 结果文件后重跑 `continue`：

```bash
rm temp/claims/<session_id>/gate2_result.json
python scripts/extract_claims_pipeline.py continue
```

### 2. Gate 5（股票代码检测）的假阳性

`gate_validate_claims.py` 的 `gate5_stock_codes()` 使用正则
`[\u4e00-\u9fff]{2,5}(?:股份|科技|电子|智能|医疗|有限)` 检测是否遗漏股票代码。
在处理板块/市场类早盘（讨论宏观方向和板块而非具体个股）时极易命中假阳性，
将通用词汇误认为公司名。

**修复**：在 `gate_validate_claims.py` 的 `NON_COMPANY` 集合中补充新的假阳性模式。
这是一个持续维护的过程——每处理一类新的 raw 文档类型都可能遇到新假阳性。

**标准修复流程**：
1. 查看具体 claim 文本，确认是假阳性（非公司名，是描述性词汇）
2. **直接编辑** `gate_validate_claims.py`，在 `NON_COMPANY` 集合中追加新模式
3. **⚠️ 不要**使用 sed 全局替换或其他自动化文本替换——可能误伤真阳性
4. 删除 `gate2_result.json` 缓存后重跑 `continue`

**参考**：`references/gate5-false-positive-patterns.md` — 已积累的模式库和按 raw 类型的预判表

### 3. Step 4 git 提交时的临时文件清理

Step 4 后处理中，`git add -A` 可能意外将 `temp/claims/` 或 `skills/` 目录下的文件 stage。

**正确做法**：
```bash
# 只 add 知识库相关文件
git add knowledge/claims/ knowledge/wiki/ scripts/gate_validate_claims.py
# 或 add 后检查，unstage 不需要的文件
git reset HEAD temp/ skills/
```

### 4. subject 字段的符号限制

`gate4_atomicity()` 禁止 subject 包含 `、` `/` `+` `&` `and`。
早盘/复盘类 claim 的主题经常需要表达对比关系（如「强修复 vs 弱修复」）。
**应对**：用中文替代禁止符号，如「强修复/弱修复」→「强修复与弱修复」。
