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

### ⚠️ 预检查：内容是否已被现有 claims 覆盖

**在 run `start` 之前**，先检查该 raw 文件的内容是否已被现有 claims 覆盖。
Bilibili 动态内容可能已被 Agent 的证券研究管线先提取（通过 `sources/raw/财经/` 路径），
导致重复提取。

```bash
# 1. 检查同日期已有哪些 claim
ls knowledge/claims/claim-YYYYMMDD-*.yaml 2>/dev/null

# 2. 阅读现有 claim 的 evidence_quote 判断是否与本 raw 重合
#    如果现有 claims 的 source_path 指向 sources/raw/财经/而非 sources/original/，
#    且 evidence_quote 与 Bilibili 动态原文完全一致 → 跳过提取
```

**决策规则**：如果已有 claims 的 statement/evidence_quote 与该 raw 高度重合，
直接跳过流程（`rm -rf temp/claims/<session>`），不做重复提取。

**注意**：`extract_claims_pipeline.py done <session>` 会拒绝清理（因为 YAML 未被移走）。
直接 `rm -rf temp/claims/<session>` 是正确做法。

**2026-06-12 实战**：10:47 动态的原始 Bilibili 内容已通过 Agent 盘中分析管线被
先提取为 `claim-20260612-002`（source_path = `sources/raw/财经/...`），
7 条候选 claim 全部被覆盖。不应再创建重复提取。

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
# ✅ 正确（结构化对象，code 为字符串带引号，含前导零）
related_stocks:
- code: '002971'
  name: 和远气体
  role: WF6小盘标的-主板可交易

# ❌ 错误（code 裸数字，前导零丢失）
  - code: 002971  # YAML 解析为整数 2971
  - code: 688981  # 虽然 6 位但类型错误

# ❌ 旧格式（字符串，Agent 无法结构化检索）
related_stocks: [中国卫星(600118)]

# ❌ 错误（嵌套在 links 下，Agent 检索不到）
links:
  wiki_pages: []
  related_stocks: []  # ← 错误位置！
```

**⚠️ `code` 必须用引号包裹为字符串**（如 `'002971'`），
不能写成裸数字。YAML 会把 `code: 002971` 当作八进制整数 → 2971。
`extract_claims_pipeline.py` 的 `_auto_format_yaml()` 已有后处理自动加引号，
Gate 3 校验也已新增 `isinstance(code_val, int)` 检查。存量文件需用 `gate_validate_claims.py --all` 扫描修复。

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
☐ 颗粒度检查：原文中每一个独立的定性判断（如"已到历史尾部区域"）都要提取为独立 claim，不要藏在同段另一条 claim 的 interpretation 中。同一段落的定量事实（"23个交易日"）和定性结论（"风险收益比在倾斜"）是两条不同的 claim

Step 2:
☐ statement 和 interpretation 中所有公司名已带 6 位代码
☐ related_stocks 已填结构化对象（无标的写 []）
☐ related_stocks 中的 code 是字符串类型（用引号包裹，如 '002971'）
☐ non-mainboard 已在 role 中标注不可交易
☐ tags 已补充（3-5 个）

Step 3:
☐ Step 3 自动完成后运行 `python scripts/gate_validate_claims.py <yaml_path>` 手动验证
☐ 特别检查：related_stocks code 未被解析为整数

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

**参考**：`references/gate5-false-positive-patterns.md` — 已积累的模式库和按 raw 类型的预判表。
`references/yaml-stock-code-leading-zero.md` — stock code 前导零丢失的修复记录。

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

### 5. Claim 颗粒度：定量事实与定性判断必须分离

同一段 raw 文本中如果同时包含**定量事实**（数字、时长、对比）和**定性判断**（结论、倾向、性价比评估），必须提取为两条独立的 claim，不能把判断塞进事实 claim 的 `interpretation` 里。

**错误示范**（2026-06-11 复盘专栏被订正）：
```
claim-a: statement="全A指数下跌23个交易日..."
          interpretation="UP从时间维度判断调整已近历史极值，风险收益比在倾斜"
```
→ "风险收益比在倾斜" 是一个独立的 market-cycle 判断，不是附属解读。

**正确做法**：
```
claim-a: statement="全A指数下跌23个交易日..."
claim-s: statement="调整已到历史级别尾部区域，风险收益比在倾斜"
```

**判断标准**：如果一条 claim 的 `interpretation` 包含了一个可以独立存在且具有检索价值的判断，就应该拆为独立 claim。

**用户偏好**：宁拆勿合。独立定性判断值得单独检索和引用，不应埋在其他 claim 的解读文本中。

### 7. 同日期 claim 编号冲突

写 `claim-YYYYMMDD-NNN.yaml` 前必须检查已有文件：

```bash
ls knowledge/claims/claim-YYYYMMDD-*.yaml 2>/dev/null | tail -3
# 如果有 -001.yaml，新文件用 -002.yaml
# 如果有 -001.yaml 和 -002.yaml，用 -003.yaml
```

**典型场景**：同一个日期有多份 raw（如早盘+盘中+复盘），编号必须递增且不重复。
Pipeline 的 step3 输出的暂存 YAML 文件名不含 NNN 段，需要 Agent 在 Step 4 手动核对后复制。

**2026-06-12 实战**：写 10:47 盘中动态的 claim 时，6/12 早盘已存在 `claim-20260612-001.yaml`，
须用 `claim-20260612-002.yaml`。如果在 Step 1 就用了重复编号，需在 step1_raw.json 和后续所有 step 中全部修正。

### 8. YAML 中 stock code 前导零丢失（code: 002971 → 整数 2971）

`_auto_format_yaml()` 使用 `yaml.dump()` 输出时，6 位字符串 `"002971"` 被写成裸数字 `code: 002971`。
YAML 1.1 解析器将前导零的数字视为八进制整数，读回时变成 `2971`。

**影响范围**：所有以 `0` 开头的 6 位股票代码（002xxx/001xxx/000xxx/300xxx 等）。

**已在** `extract_claims_pipeline.py:_auto_format_yaml()` 中新增后处理：
```python
# 自动加引号修复：code: 002971 → code: '002971'
fixed = re.sub(r'(?m)^(  - code: )0(\d{5})\s*$', r"\1'0\2'", raw)
fixed = re.sub(r'(?m)^(  - code: )([1-9]\d{5})\s*$', lambda m: f"  - code: '{m.group(2)}'", fixed)
```

**防御**：`gate_validate_claims.py:gate3_related_stocks()` 新增 `isinstance(code_val, int)` 检查，
在 Gate 3 阶段捕获遗留的整数 code。

**存量扫描**：
```bash
python scripts/gate_validate_claims.py --all --step 2 | grep "是整数类型"
```
