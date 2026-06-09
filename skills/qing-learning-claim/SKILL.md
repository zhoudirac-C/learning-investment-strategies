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
☐ statement 中公司名已带 6 位代码
☐ related_stocks 已填结构化对象（无标的写 []）
☐ non-mainboard 已在 role 中标注不可交易
☐ tags 已补充（3-5 个）

Step 4:
☐ 已更新 wiki/index/log
☐ git commit 已推
```
