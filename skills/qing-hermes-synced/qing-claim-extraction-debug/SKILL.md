---
name: qing-claim-extraction-debug
description: >-
  Debug patterns and pitfalls in the claim extraction pipeline
  (extract_claims_pipeline.py). Use when Gate 1/2/3 keeps failing,
  JSON parsing errors, cache issues, or NON_COMPANY false positives.
  NOT a replacement for qing-learning-claim — this is the debug companion.
---

# qing-claim-extraction-debug

## Scope

Companion to `qing-learning-claim` skill. This skill captures **debug patterns**
that are too specific to the extraction pipeline's implementation quirks to live
in the higher-level workflow skill. Use it when Gate 1/2/3 rejections stall
the pipeline.

## 1. JSON quoting

### Symptom
`json.decoder.JSONDecodeError: Expecting ',' delimiter` when running Gate 1.

### Root cause
Chinese text in `step1_raw.json` contains ASCII `"` inside string values:

```json
// ❌ Inner "最坏已排除" closes the outer string
"interpretation": "这与7/21早盘"最坏已排除"的定位一致"
```

### Fix: Option A — Replace with Chinese brackets
Replace inner quotes with Chinese brackets **before** writing the JSON:

```json
// ✅
"interpretation": "这与7/21早盘「最坏已排除」的定位一致"
```

### Fix: Option B — Use json.dumps()
Write the JSON programmatically via `json.dumps()` which auto-escapes inner quotes.
Best for new extraction sessions; not always practical when editing existing step files.

### Fix: Option C — Regex bulk replace (for Chinese quotation marks)
When the inner quotes are meant as Chinese quotation marks (« ... » or "……"),
replace ASCII `"` with Unicode U+201C/U+201D using Python regex:

```python
import re
LEFT, RIGHT = '\u201c', '\u201d'
# ⚠️ CJK punct 类必须包含 \u2013-\u2014（破折号）、\u2026（省略号）、\u00b7（间隔号）！
# 否则 `是"极端工具"——` 这种闭合引号后紧跟 —— 的文本会匹配失败
CJK_PUNCT = (
    '\u4e00-\u9fff'          # CJK Unified Ideographs
    '\u3000-\u303f'          # CJK Symbols and Punctuation
    '\uff00-\uffef'          # Fullwidth forms
    '\u2013-\u2014'          # en dash, em dash  ← 必加（中文常用 —— 收尾）
    '\u2026'                 # ellipsis          ← 必加
    '\u00b7'                 # middle dot
)
# Pattern: CJK_char + " + (non-newline content) + " + CJK_char/punct
pattern = re.compile(
    f'([{CJK_PUNCT}])\"([^\"\\n]+?)\"([{CJK_PUNCT}])'
)
fixed = pattern.sub(lambda m: m.group(1) + LEFT + m.group(2) + RIGHT + m.group(3), text)

# ⚠️ 必须多轮迭代直到稳定（嵌套场景 `说"XX"是"YY"` 会留下未处理的引号对）
for _ in range(5):
    new = pattern.sub(lambda m: m.group(1) + LEFT + m.group(2) + RIGHT + m.group(3), fixed)
    if new == fixed:
        break
    fixed = new
```

**2026-07-30 实战教训**：第一版正则（CJK 类不含 `\u2014`）在
`次新和可转债是"极端工具"——要么...` 上**静默失败**——闭合引号后紧跟 `——`
不在字符类内，re.sub 不报错只是不替换，JSON 仍解析失败，容易被误判为
"还有别的引号问题"而反复修。加上 `\u2013-\u2014\u2026\u00b7` 后一次通过。

This regex catches patterns where `"` appears between CJK characters — typical of
video transcripts and long-form text where Chinese quotes are mis-typed as ASCII.

### Common pitfall: multiple instances
Sessions with 10+ claims can have 3-5 unescaped quote instances. Option C (regex) is
most efficient for bulk fixes. Run validation after fix:

```bash
python3 -m json.tool temp/claims/<session>/step1_raw.json
```

## 2. Gate 2 stock code format

### Symptom
Gate 2 returns `"紫光股份 在文本中出现但未标注 6 位代码"` despite the code being right next to the name.

### Root cause
The Gate regex requires `（(\d{6})）` or `((\d{6}))` — code in **parentheses**:

```text
// ❌ Gate cannot find the code
超节点（紫光股份000938）

// ✅ Gate can match (\d{6}) in parens
超节点（紫光股份(000938)）
```

### Fix
Always wrap codes in `公司名(6位代码)` format across **both** `statement` and `interpretation` fields.

### Programmatic annotation: lookahead bug (2026-08-02 复盘实战)

When auto-annotating company names with codes via regex `sub()`, a naive negative
lookahead silently skips valid names and Gate 2 reports "X 在文本中出现但未标注 6 位代码":

```python
# ❌ 负向前瞻 (?![（(]) 会跳过"名字后跟中文括号"的正常情况
pattern = re.compile(name + '(?![（(])')
# "捷成股份（红果短剧..." 中"捷成股份"后紧跟"（" → 被跳过，未替换！

# ✅ 只跳过"已带数字代码"的情况（如 普联软件(300996) 防重复标注）
pattern = re.compile(re.escape(name) + r'(?!\s*[（(]\d{5,6}[）)])')
```

实战表现：25 条 claims 中 1 处（捷成股份）因名字后跟中文括号描述而漏标，其余全部成功。
排查方法：`re.findall(r"([\u4e00-\u9fff]{2,5}(?:股份|科技|电子|智能|医疗|有限))", text)`
预扫描出所有未带 `(\d{6})` 的名字，对照 Gate 报错确认是漏标还是假阳。

### Non-A-share codes: 港股/未上市 (2026-08-02 实战)

Gate 2 校验 `code_refs = re.findall(r"[（(](\d{4,6})[）)]", text)` 且 `len(code) != 6` 报错。
- **港股代码是 5 位**（金蝶国际 00268、明略科技 02718、明略昭辉无码）→ 不能放 related_stocks，
  文本中也**不要**标注 `(00268)`，否则 Gate 2 报 "股票代码 '00268' 不是 6 位"。
- 处理：A股知识库不收录港股 → 从 related_stocks 移除；公司名（如 明略科技）加入
  `gate_validate_claims.py` 的 `NON_COMPANY`（注释标"港股"），文本保留公司名不标代码。
- 判定方法：`searchapi.eastmoney.com` 返回 `MktNum=116` → 港股；`MktNum=1` → 沪市；`0` → 深市。

### False positives: NON_COMPANY
If the Gate flags a company name that is genuinely NOT a company, add it to
`gate_validate_claims.py`'s `NON_COMPANY` dict (lines ~326-397).

#### Understanding the Gate regex
The Gate finds ALL 2-5 character Chinese names ending with specific suffixes:
```python
company_names = re.findall(r"([\u4e00-\u9fff]{2,5}(?:股份|科技|电子|智能|医疗|有限))", text)
```
This means ANY Chinese text fragment matching the pattern gets flagged — not just real
companies. The flagged text is the **exact fragment** from the combined
`statement + interpretation` text, not the full word.

#### How to read error messages
```
# Text fragment from combined statement + interpretation
- '回落有限' → catches "有限" as company suffix (text: "回落幅度相对周二涨幅相当有限")
- '了两家中游电子' → catches "电子" (text: "转载了两家中游电子标的的产业信息")
- '金认为这是科技' → catches "科技" (text: "UP认为这是科技内部换手")
```
Add the exact fragment from the error message — do NOT add full words or prefixes.

#### Common additions by pattern type
```python
# Pattern 1: "科技" as sector/industry term (most common)
"后续科技", "它们是科技", "的老登股与科技",
"双创随科技",  # "双创随科技股" → fragment "科技"
"即今天科技", "金认为这是科技",

# Pattern 2: "电子" as industry term (not a company name)
"了两家中游电子",  # "中游电子标的" → fragment

# Pattern 3: "有限" in text (not company suffix)
"回落有限",  # "涨幅相当有限" → fragment

# Pattern 4: real company mentioned in interpretation but already coded in statement
"心品种紫光股份",
# Rule of thumb: if the full company name(6位代码) appears correctly in statement,
# the interpretation mention is a duplicate — add the fragment to NON_COMPANY.

# Pattern 5: "智能" as tech domain (not a company)
"北京市加快智能", "提出夯实智能", "芯片的通用智能",

# Pattern 6: unlisted subsidiary mentioned in interpretation (covered by parent company's related_stocks)
"金胜电子", "收购的金胜电子",  # owned by 恒尚节能(603137), not listed separately
```

#### Full NON_COMPANY update workflow

NON_COMPANY hits are a **NORMAL step in every extraction session** — especially for
long-form analytical text (晚间复盘/专栏). They are NOT errors in your claims.
Treat them as expected maintenance.

```
1. Read each error message → extract the exact text fragment
2. Classify each fragment:
   - Real listed company name → add 6-digit code to statement/interpretation
   - Industry/plate/generic term → add fragment to NON_COMPANY set in gate_validate_claims.py
   - Unlisted subsidiary → already covered by parent company's related_stocks → add to NON_COMPANY
3. After updating NON_COMPANY, clear gate cache and retry:
   ```
   rm -f temp/claims/<session>/gate2_result.json
   python scripts/extract_claims_pipeline.py continue
   ```
4. If more fragments surface in the retry → repeat steps 1-3
   (Gate 2 only reports the FIRST batch of misses per run)
```

**Why this happens**: The Gate regex `([\\u4e00-\\u9fff]{2,5}(?:股份|科技|电子|智能|医疗|有限))`
catches ANY 2-5 Chinese chars before those suffixes. Long-form text like 晚间复盘
inevitably contains "空间有限", "看空科技", "近期科技", etc. in interpretation
paragraphs.

**How to minimise**: In Step 2, pre-emptively check interpretation text for
fragments matching `[2-5汉字]+(科技|电子|智能|有限)` and batch-add them
to NON_COMPANY before running Gate 2. This saves one round-trip.

## 3. "+" in subject blocks Gate 1

### Symptom
Gate 1 returns `"subject 含 '+' — 可能包含多主题"`.

### Common triggers

| Scenario | Before | After |
|----------|--------|-------|
| Growth rate | `+23.2%` | `涨23.2%` |
| Two sub-topics | `A+B双驱动` | `A与B双驱动` |
| Connection | `A+B+C` | `A与B与C` |

### Fix
Subject must not contain `+`, `/`, `、`, `&` — any of these triggers the multi-theme checker.

## 4. Pipeline cache blocking retries

### Symptom
After fixing step1_raw.json or step2_enriched.json and running `continue`, the Gate
outputs the **same error list** as before the fix.

### Root cause
`gate1_result.json` / `gate2_result.json` are read first to avoid re-running. The cache
still holds the old result.

### Fix
```bash
rm -f temp/claims/<session>/gate1_result.json
rm -f temp/claims/<session>/gate2_result.json
python scripts/extract_claims_pipeline.py continue
```

## 5. Step 3 YAML note field quoting

### Symptom
YAML lint error after Step 3: `YAMLError: while scanning a quoted scalar`

### Root cause
The `note:` field in direction_pool.yaml contains unmatched quotes or special chars:
```yaml
# ❌ single quote breaks the double-quoted scalar
note: "...'超节点分歧'..."
```

### Fix
Remove or replace apostrophes/single quotes inside YAML double-quoted values.
Use `yaml.safe_load()` to validate before writing.

## 6. Long-form analytical text (晚间复盘/专栏) — batch false-positive pattern

### Symptom
After writing 10-20 claims from an evening review, Gate 2 returns 8-15
NON_COMPANY errors, all sector/industry terms from interpretation fields.

### Root cause
Long-form text (~300 lines) with detailed sector analysis generates many
[2-5汉字]+(科技|电子|智能|有限) fragments in interpretation. Gate 2's
regex catches them all in one pass.

### Before running Gate 2 on long-form text
Scan interpretation fields for fragments matching the pattern and batch-add
them to NON_COMPANY in the gate script before the first Gate 2 run. This
saves one round-trip per extraction session.

### Real-world example
See `references/2026-07-23-extraction-session-patterns.md` for the exact
fragments added from the 7/23 evening review (16 claims, ~12 false positives).

## 7. 寓言包裹Structured Content — mixed-content extraction

### Symptom
A post starts with 寓言/心理按摩 (60%+ of content) but ends with structured
claims (specific stock levels, market judgments). Agent might skip the entire
post due to low-info rules.

### Fix
Read the full post body. Structured claims often appear in the final paragraphs
after the motivational framing. Extract only the structured parts; mark the
寓言 portion as "read, understood, not extracted."

### Decision rule
| Has structured content? | Action |
|------------------------|--------|
| Pure 寓言 throughout | Skip entirely (mark unprocessed: false) |
| 寓言开头 + structured结尾 | Extract structured claims only |
| Interspersed throughout | Extract each structured claim, skip psychological framing |

### Reference
`references/2026-07-23-extraction-session-patterns.md` section 1331 Mixed-Content Post

## 8. run_discover_with_progress.sh syntax error

### Symptom
Running the shell wrapper for discovery fails:
```
bash scripts/run_discover_with_progress.sh
```
Error about parenthesis mismatch on line 27.

### Workaround
Call the Python script directly instead:
```bash
cd ~/learning-investment-strategies
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing
```

The --all-missing flag ensures only new claims (without last_discovered) are processed.
Old claims are automatically skipped.

### Verification
Check output ends with:
```
Done. Found N relations (supersedes/contradicts + supplements).
```

## 9. Reference: new extraction session patterns

See `references/2026-07-29-extraction-session-patterns.md` for patterns from this session.

## 10. Reference: 7/29 video + evening-review false positives (batch B)

See `references/2026-07-30-supplement-false-positives.md` — 21 additional NON_COMPANY
fragments from the 7/29 video《科技该反弹了》(19 claims) and the 2205 复盘专栏
(18 claims). Key takeaway: **each raw type has its own phrasing patterns; fragments
don't overlap across 早盘/复盘/视频 types**, so the NON_COMPANY set must keep
accumulating per type. Video transcripts have unique patterns like "反弹中科技"
and "把科技仓位" that never appear in 复盘/早盘 text.

## 11. Reference: 7/31 早盘 false positives (batch C)

See `references/2026-07-31-morning-column-false-positives.md` — 14 additional
NON_COMPANY fragments from the 7/31 早盘专栏 (19 claims). Key takeaway: **早盘 text
is the heaviest "科技" generator of all types** because tech is usually the subject
("开盘若出现科技", "这是一次给科技", "不是给科技"), and "消费电子"/"人工智能"
as sector terms also trigger. Pre-scan interpretation fields for `[2-5汉字]+(科技|电子|智能)`
before the first Gate 2 run to save a round-trip — the full pre-scan recipe is in §6.

## 12. Reference: 8/2 复盘 session patterns

See `references/2026-08-02-extraction-session-patterns.md` — 25-claim 充电专属专栏
复盘实战：B站 `pub_time` 相对时间坑（用 `pub_ts`）、专栏正文提取防御
（`module_content` 可能为 None）、annotate lookahead bug、港股 5 位代码处理
（金蝶国际 00268/明略科技 02718 → NON_COMPANY）、Step 4 单日单文件惯例
（`claim-YYYYMMDD-001.yaml` 含当日全部 claims）。

## 13. NON_COMPANY 片段规则：必须加完整匹配片段（2026-08-03 早盘+盘中实测）

Gate 2 报错的片段**就是正则的完整匹配**（`[\u4e00-\u9fff]{2,5}(科技|电子|智能|股份|医疗|有限)`），
不是公司名本身。只加公司名/短子串**不会消除错误**，必须加报错信息里的完整片段：

```
❌ 只加 "宇树科技"     → 报错仍显示 "器人看宇树科技"（5字前缀+科技）
❌ 只加 "对全球科技"   → 报错仍显示 "前置对全球科技"
✅ 必须加 "器人看宇树科技"、"前置对全球科技"（与报错完全一致）
```

**2026-08-03 早盘 15 条**：一次性加 14 个片段（核心框架是科技 / 如果理解科技 /
的反弹是让科技 / 大金融与科技 / 重新走强而科技 / 形态本质是科技 / 绿被定性为科技 /
且它与科技 / 维持非科技 / 宇树科技 / 器人看宇树科技 / 前置对全球科技 / 对全球科技）。

### 非 A 股公司也进 NON_COMPANY（真公司但无 6 位 A 股代码）

不是假阳性的公司也会被 Gate 2 报缺代码——**外国股票、未上市公司**没有 6 位
A 股代码可标，必须进 NON_COMPANY（加注释说明原因）：
- 韩股：三星电子、SK海力士（2026-08-03 盘中，需加 "以及三星电子"、"三星电子和SK海力士" 等完整片段）
- 未上市/申购中：宇树科技（8/10 才申购，无代码）
- 港股 5 位代码：金蝶国际 00268、明略科技 02718（见 §12，同规则）
- **美股字母代码：莫德纳 MRNA、默沙东 MRK（2026-08-20 早盘）**——除文本标注外，
  **related_stocks 的 code 字段也被 Gate 校验为纯 6 位数字**，放 MRNA/MRK 直接报
  `related_stocks code='MRNA' 不是纯数字字符串`；东财 SecurityTypeName=美股/日股/韩股
  的一律不进 related_stocks，文本完整匹配片段进 NON_COMPANY（注释 "美股/日股"）

与"板块描述假阳性"的区别：这些是**真公司**，进 NON_COMPANY 只是因为没有可标注的
A 股代码，interpretation 里可注明"未上市/韩股"保留信息完整性。

## 14. Reference: 8/3 早盘+盘中 session patterns

See `references/2026-08-03-extraction-session-patterns.md` — 早盘 15 条 + 盘中
3 条动态 11 条合并当日 26 条实战：NON_COMPANY 完整片段规则（科技语境 14 片段 +
韩股三星电子/SK海力士无 A 股代码）、单 session 混多条 raw（source_path 各自独立）、
同日合并 yaml 配方、服务端模式手动分步同步 + 索引脚本杀 Agent 收尾动作。
（2026-08-03 复盘追加见同一 reference 文件"复盘补充"节。）

## 15. Gate 1 校验规则：subject 含 '+' 被拒 + 缓存必须清（2026-08-03 复盘实测）

### 15.1 subject 含 '+' = 多主题嫌疑

Gate 1 拒绝 subject 中含 `+` 的 claim（"可能包含多主题"），即使语义上
`+` 只是连接词：

```text
❌ subject: 情形A：量能回升+强者恒强→硬件调整进入尾声
✅ subject: 情形A：量能回升与强者恒强，硬件调整进入尾声
```

**Fix**：写 subject 时用"与/及"代替 `+`（`→` 可保留）。**topic 字段同样建议
规避**（Gate 1 虽只报 subject，但 topic 中的 `+` 无必要）。statement/
interpretation 正文中的 `+` 不受限。

### 15.2 Gate 1 结果缓存

**症状**：修改了 step1_raw.json（如上述 subject 修复）后 `continue` 仍输出
**与之前完全相同的错误列表**。

**根因**：Gate 1 结果缓存在 `temp/claims/<session>/gate1_result.json`，
pipeline 读缓存跳过重跑——与 Gate 2/3 的缓存坑（qing-learning-claim 已知坑点 1）
同机制，但 Gate 1 的缓存同样存在。

**Fix**：

```bash
rm -f temp/claims/<session>/gate1_result.json   # 以及 gate2/gate3_result.json
python scripts/extract_claims_pipeline.py continue
```

修改任何 step 产物后，**对应 Gate 的 result 缓存都要清**，别只清 gate2。

## 16. 动态提取覆盖检查（"今天有没有动态没提取claim"）

对比 B站动态列表 vs claims 库时：SESSDATA 在 `~/.hermes/bilibili_sessdata.txt`（**不在 .env**）；当前 API 响应里动态 ID 在 `id_str`（`desc` 为 None）、`pub_ts` 是字符串需 int()；单日多条 claims 合并在一个 YAML（数文件内部 `id: claim-` 而非文件数）；提取会话卡 `state: init` + `attempts_step1: 0` = 漏提。完整工作流见 `references/dynamic-coverage-gap-check.md`。

## 17. 早盘专栏 Gate 假阳性与坑位（按日期归档）

早盘/复盘专栏的"管制/涨价"主题段是 Gate 1/2 假阳性高发区，按日期归档在 references/：
- `2026-08-07-extraction-session-patterns.md` — 行业概念词假阳性（磷化铟与电子/存储仍是科技/核心品种向电子）；**Gate 1 新坑：subject 含 `/` `+` 被拒**（三情形/三观察变量类 subject 天然含分隔符，改"与/及"通过）
- `2026-08-03-extraction-session-patterns.md` — "科技/智能"语境词 32 片段；同日多来源合并流程；同步管线三次验证
- `2026-08-10-extraction-session-patterns.md` — 当日 46 条（早盘22+晚间复盘24）编号续编；subject Latin "/"（情形A/B）；Gate 5 校验 interpretation 全文；NON_COMPANY 批次15；discover 同日矛盾自动发现（晚间修正早盘）
- `2026-08-11-extraction-session-patterns.md` — subject Latin `+`（超跌+事件催化）、
  科技/非科技方向对比句式 NON_COMPANY 批次16、新日期首条提取=新文件（cp 非 tail）、
  影视预期演进 discover 关系链（3天3变）
- `2026-08-18-extraction-session-patterns.md` — 早盘 26 条 + 09:27 动态 4 条 + **午盘 13:31 动态 8 条（031-038）**；
  NON_COMPANY 批次 10+2+2（词根+完整串双加才通过，§13 规则再验证）；
  宏观技术型早盘特有短语（纪要偏鹰压科技/今日开盘对科技）；
  午盘新增假阳性：\"度大概率也有限/调整幅度有限\"（\"有限\"后缀第 N 次出现，呼应 §21）；
  单日三文件惯例（001=早盘专栏/002=09:27/003=午盘，编号跨文件连续）；
  B站核对走脚本函数非裸 curl
- `2026-08-18-extraction-session-patterns.md` **复盘追加（22:32 复盘专栏 32 条 039-070，当日四文件 001-070 编号连续）**：
  NON_COMPANY 复盘批 4 条：\"二浪回调时科技\"\"线强势之后科技\"\"全线强势后科技\"\"度可能弱于科技\"——
  复盘专栏\"科技内部仍有分支/防御强势之后科技/强度可能弱于科技\"句式是新增假阳来源，
  与早盘\"科技\"假阳不重叠（印证 §10 每类文本有自己的句式）；
  **复盘专栏是大批量假阳主产地**（32 条长文 → Gate 2 一次报 13 个缺代码：真公司如金禄电子/中石科技/珂玛科技/航天电器
  需补 `(6位代码)` 到 statement+interpretation 两处，科技语境假阳 4 条进 NON_COMPANY——
  真公司+假阳混报时**先批量 API 核实代码再统一补**，避免多次往返，§18 流程复用）；
  单日四文件惯例固化（001=早盘/002=09:27/003=午盘/004=复盘），新 raw 永远新文件（cp 非追加）
- `2026-07-31-morning-column-false-positives.md` / `2026-07-30-supplement-false-positives.md` — 早盘专栏历史假阳性

**通用规律**：遇 Gate 2 报"X 在文本中出现但未标注 6 位代码"，先判断 X 是行业/材料/概念词（磷化铟、存储、电子化学品、科技、智能、有限）还是真公司名——行业词批量补 NON_COMPANY，补的片段必须与报错完全一致（完整正则匹配片段，见 §13）。

## 18. 股票代码必须 API 核实，禁止凭记忆写（2026-08-12 晚间复盘实测）

### 症状
Step 1 凭记忆写的代码通过 Gate 1/2/3 全部校验（格式合法 6 位），
但**代码是错的**——百花医药实际是 600721，凭记忆写成 600466。
Gates 只校验格式（6 位数字 + 括号），**不校验代码与公司名的对应关系**，
错误代码会静默入库。

### 根因
Gate 5 正则只检查"公司名后跟 `(6位数字)`"，不查代码真实性。
错代码 100% 通过管线，直到下游检索/人工核对才暴露。

### Fix（强制）
**每条 claim 的公司代码必须查东财 suggest API 确认，禁止凭记忆**：

```bash
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=$(python3 -c 'import urllib.parse; print(urllib.parse.quote("百花医药"))')&type=14&count=1"
# → QuotationCodeTable.Data[0].Code = 600721
```

- Step 1 写草稿时就查，不要等 Step 2——Step 2 的"补代码"是核对不是首查
- 批量查询用 execute_code 循环（一次脚本查完所有公司名），返回 `Name Code MktNum`
- MktNum 判断板块：1=沪市、0=深市（主板），科创板/创业板标的 role 标注不可交易
- 记忆中的代码（哪怕是"很熟的票"）也要过 API——本次就是熟票出错

### 附带教训
同日期多文件编号：`claim-20260812-001.yaml`（早盘 001-025）后，
晚间复盘从 **026 起** 写入 `claim-20260812-002.yaml`（新文件，非追加）。
核对编号 = 看当日所有 YAML 的最后一个 id +1，不是"文件序号+1"。

## 19. 跨零点"今晚复盘"语义（2026-08-13 00:14 实测）

用户在 00:14 说"今晚复盘"，指的是**前一日 22:19 的晚间动态**（8/12），
不是 8/13 当天（还没发）。定位流程：
1. `date` 确认当前北京时间（跨零点时"今晚"= 前一日晚）
2. 拉 B站 feed 列表按 `pub_ts` 找最新动态 → 确认发布时间
3. 本地 `sources/original/bilibili/` 可能已有该动态（`unprocessed: true` 但已抓取），
   直接复用，别重复抓取

## 20. B站 feed 静默空响应排查（2026-08-12 晚间复盘实测）

`fetch_bilibili_up_v2.py` 跑完**无任何输出且 exit 0**，可能原因按序排查：
1. **API 412 风控**：`curl` 裸请求 feed API 返回 412；脚本内 `build_cookie()` 完整模板
   （buvid3/b_lsid/buvid4/sid 等 20+ 字段）才正常 → **不要用 curl 单独测 SESSDATA**，
   始终走脚本或完整 Cookie 模板
2. **SESSDATA 位置**：`~/.hermes/bilibili_sessdata.txt`（**不在 .env**，.env 里 BILIBILI_SESSDATA 为空）
3. 验证登录态：`curl /x/web-interface/nav` 返回 `isLogin: true` 即 SESSDATA 有效
4. 脚本正常时输出 `NEW_DYNAMIC: <path>`；静默 + exit 0 = 无新动态（state 文件 `processed_ids` 已含最新），
   不是失败——先查 `~/.hermes/bilibili_up_state.json` 的 `last_dynamic_id` 再决定是否补抓

## 21. 重写避假阳（不碰 NON_COMPANY 的替代法）+ "有限"是第六个后缀（2026-08-13 复盘专栏实测）

### "有限"也是 Gate 5 后缀（最常被忽略）

Gate 5 正则的 6 个后缀是 `股份|科技|电子|智能|医疗|有限`。**"有限"=limited**，
是市场分析里最无法回避的词（"空间有限/涨幅有限/范围有限/相对有限"），
写 statement/interpretation 时极容易触发。§2 只把它当 Pattern 3 一笔带过，
实战里它是仅次于"科技"的第二大假阳来源——本 session 就命中"相对有限"（claim-027）、
"范围有限"（claim-026 interpretation）两处。

### 重写技巧：把后缀词放到标点后，让匹配塌缩到已在 NON_COMPANY 的 2 字词

正则 `[\u4e00-\u9fff]{2,5}(科技|电子|智能|医疗|有限)` 贪心抓后缀词前 2-5 个汉字。
**若后缀词紧跟在标点（。、：；——，）之后，前面 0 个汉字 → 匹配 = 后缀词本身**，
而"当前科技"等 2 字词大多已在 NON_COMPANY，直接通过，无需改 `gate_validate_claims.py`。

实战四条：

| 原文片段 | Gate 报错 | 重写 |
|---------|----------|------|
| 带动科技板块 | 带动科技 | 科技板块随之走强。科技就有了…（"科技"挪到句号后） |
| 标签是医疗服务 | 签是医疗 | 三个标签分别是：医疗服务业的后周期属性（"医疗"挪到冒号后） |
| 普通级电子布 | 通级电子 | 普通级玻纤布（换同义词，避开"电子"后缀） |
| 收购的岚创科技 | 收购的岚创科技 | 收购的标的公司——岚创科技（破折号断在"岚创科技"前，匹配塌缩为"岚创科技"） |

### 什么时候重写 vs 加 NON_COMPANY

- **板块/概念词**（科技/电子/智能/有限/医疗当普通名词）→ 优先重写，省一次
  `gate_validate_claims.py` 的代码改动 + git commit
- **真·未上市/非 A 股公司**（岚创科技这种收购标的）→ 仍要加 NON_COMPANY（加注释），
  但**用破折号/冒号把公司名前的汉字断掉**，让匹配塌缩到"岚创科技"这 2 字——否则贪心
  抓到"收购的岚创科技"（5 字前缀）仍会报错（呼应 §13 的完整片段规则）
- 重写后若句子生硬，退回加 NON_COMPANY 完整片段

### 程序化写 step2（批量 20+ 条时不重抄整段 JSON）

24 条 claims 时，用 execute_code 读 step1_raw.json + dict 映射（id → related_stocks/tags）
合并写 step2_enriched.json，避免手工重抄 24 段 JSON（本 session 从手写改脚本后零拼写错）：

```python
import json
claims = json.load(open("temp/claims/<session>/step1_raw.json"))
enrich = {"claim-...-024": ({"related_stocks": [...], "tags": [...]}), ...}
for c in claims:
    c["related_stocks"] = enrich[c["id"]]["related_stocks"]
    c["tags"] = enrich[c["id"]]["tags"]
json.dump(claims, open("temp/claims/<session>/step2_enriched.json", "w"), ensure_ascii=False, indent=2)
```

### "unprocessed" 标记惯例（别被误导）

`sources/original/bilibili/*.md` 的 frontmatter `unprocessed: true` **处理后从不翻 false**
（8/12 文件已有 claims 却仍 `unprocessed: true`）。判断"某动态是否已提取"的可靠信号是
**`knowledge/claims/` 里是否有 source_path 指向该动态的 claim**，不是 frontmatter 标记。

## 22. 充电专属专栏手动拉取：文章 API 是占位符，必须走 fetch_article_content（2026-08-19 早盘实测）

### 症状
动态列表能拿到 article id，但两个 API 都只返回 18 字占位符：
- `api.bilibili.com/x/polymer/web-dynamic/v1/detail` 的 `article.desc` = "请将App客户端升级至最新版本后观看"
- `api.bilibili.com/x/article/view?id={aid}` 的 `data.content` 同样是占位符（正文长度 18）

### 根因
充电专属专栏正文不通过公开文章 API 下发，只嵌入 read 页面 HTML。

### 正确姿势
用 `scripts/fetch_bilibili_up_v2.py` 的 `fetch_article_content(article_id, sessdata)`：
- 抓 `https://www.bilibili.com/read/cv{article_id}` 页面
- 正则提 `window.__INITIAL_STATE__` → `detail.modules[].module_content.paragraphs[].text.nodes[].word.words`
- 返回拼接全文（本次 5332 字成功）

```bash
export BILIBILI_SESSDATA=$(cat ~/.hermes/bilibili_sessdata.txt)
PYTHONPATH=src .venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from fetch_bilibili_up_v2 import fetch_article_content
print(fetch_article_content('<article_id>', '$BILIBILI_SESSDATA'))"
```

拿到全文后按 frontmatter 模板落盘 `sources/original/bilibili/` 再走 C2 管线
（手动拉取时 cron 可能还没抓到该 raw，检查 `find sources/original/bilibili/` 是否已存在）。

## 23. Gate 2 新报错：statement 有代码但 related_stocks 为空（2026-08-19 盘中实测）

### 症状
```
statement 中标注了 A 股代码但 related_stocks 为空
```

### 根因
Step 2 批量做 `公司名(6位代码)` 文本标注时，related_stocks 列表没同步配置
（rs_cfg 缺该 claim id，但 statement 已提到该股）。

### 排查
```python
import json, re
d = json.load(open('<session>/step2_enriched.json'))
pat = re.compile(r'\((\d{6})\)')
for c in d:
    codes = set()
    for f in ['statement','evidence_quote','interpretation']:
        codes.update(pat.findall(c[f]))
    missing = codes - {r['code'] for r in c.get('related_stocks',[])}
    if missing: print(c['id'], '缺:', missing)
```

### Fix
补 related_stocks（code/name/role），删 gate2 缓存重跑。与 §2 的"补代码"
是同一件事的两面：**文本标注和 related_stocks 必须一起补**。

## 24. 置顶评论也是 claim 源（图片动态）

图片动态 raw 的 `## 置顶评论` 段（UP 自评）不要漏看——常比正文更积极
（8/19 09:59 动态：正文"不着急抄"、置顶"这个地方可以抄一波了"），
可提取为独立 operation claim（confidence: medium）。

## 25. Reference: 8/19 提取会话（早盘专栏 + 3 盘中动态）

See `references/2026-08-19-extraction-session-patterns.md` — 当日 4 文件 42 条
（001 早盘专栏 24 条 + 002/003/004 盘中动态 18 条）：充电专栏手动拉取
（fetch_article_content 走 read 页面）、NON_COMPANY 批次 19（早盘 14 条
"X科技"句式 + 盘中"亏损风险有限/指数跌幅有限"）、Gate 2 新报错
（statement 有码但 related_stocks 空）、置顶评论提取、时间语义
（12:03 动态建议 10:20 抄底=盘后总结非未来指令）。

## 26. Reference: 8/19 复盘 + 8/20 早盘提取会话

See `references/2026-08-20-extraction-session-patterns.md` — 8/19 复盘 30 条
（043-072）+ 8/20 早盘 27 条 + 09:54 动态 3 条：**美股/日股字母代码不能进
related_stocks**（code='MRNA' 不是纯数字 → 从 related_stocks 移除，文本片段进
NON_COMPANY 注释"美股"）；复盘专栏科技状态短语批（"抛压集中在科技/高度集中在科技"）；
早盘隔夜外盘段=美股公司名高发区（迈威尔/希捷/西数等全走 NON_COMPANY 完整片段）。
当日文件惯例：8/20 两条 raw=两文件（001 早盘/002 09:54），编号跨文件连续。

## 27. Reference: 8/20 复盘提取（21:58 图片动态 = 完整复盘）

See `references/2026-08-20-extraction-session-patterns.md`"复盘补充"节 — 8/20 复盘
19 条（031-049，claim-20260820-003.yaml）。

### ⚠️ "今晚复盘"可能不是专栏，是图片动态（2026-08-20 21:58 实测）

用户说"提取今晚的复盘动态"时，最新动态可能是 **DYNAMIC_TYPE_DRAW（图片动态）而非
ARTICLE（专栏）**——8/20 的复盘就是以图片动态发布（`1238651014681198595`，标题
"一、指数定环境：缩量4317亿的修复…"），内容为完整复盘（五章节+明日跟踪清单）。
**判定依据是内容不是类型**：列表拿到最新动态后直接看 raw 正文（cron 已抓），
正文结构像复盘（指数/板块/个股/明日清单）就按复盘流程提取，不因类型是图片就跳过。

### NON_COMPANY 追加（19 条复盘仅 1 条假阳）

```
"只能把有限",   # "只能把有限筹码压缩在CPO窄范围内" — "有限"后缀动词短语变体
```
复盘 19 条长文只报 1 条假阳（对比 8/19 复盘 30 条报 6 条）——原因是本篇复盘
板块段以公司名为主（长飞光纤/康泰生物/神奇制药等真公司补码），
"科技"状态短语少（"宽度修复"替代了"科技"高频出现）。印证 §6 预判：
**先看 raw 里"科技/有限"出现频率再预估假阳批次大小**。

### 个股代码批量核实 27 家一次通过

19 条复盘含 27 个新个股（长飞光纤 601869/康泰生物 300601/神奇制药 600613/
哈药股份 600664/金健米业 600127 等），execute_code 循环东财 API 一次查完，
全部命中（含科创板 688xxx/创业板 300xxx）。科创板/创业板 role 标注"不可交易"。

## 28. Reference: 8/21 早盘提取（08:49 图片动态 = 完整早盘结构）

See `references/2026-08-21-extraction-session-patterns.md` — 8/21 早盘 21 条
（001-021，claim-20260821-001.yaml）。

### 早盘 DRAW 也可能是完整结构化内容

与 §27 同理但换一侧：8/21 早盘是 **DYNAMIC_TYPE_DRAW（图片动态）**，但正文
六章节齐全（隔夜与开盘预判 → 指数三要素 → 板块定方向 → 消息面 → 三情形 →
周五预案）。**判定依据是内容不是类型**——早盘 DRAW 结构完整就按完整早盘流程
提取，不要因类型是图片就降级或跳过。

### NON_COMPANY 批次 23（8/21 早盘 5 片段）

早盘隔夜外盘段（美股公司名高发区）+ "科技/医疗"状态短语：

```
"中涌入高位科技",    # "前期集中涌入高位科技股的增量资金"
"落警惕高位科技",    # 外围给信号场内不接语境
"弹首先是让科技",    # "科技的反弹首先是让科技止跌"
"美股医疗",          # "美股医疗保健板块领跌"
"隔夜美股医疗",      # 同主题另一处措辞变体
```

注意"美股医疗"双前缀变体——同一主题在 statement 与 interpretation 措辞不同
产生两个片段，都要加（§13 规则）。21 条仅 5 条假阳一次通过，量级符合 §6 预判
（早盘 3-5 条；隔夜段是美股公司名固定假阳来源）。

### 单日文件数可变惯例

8/19 五文件（001 早盘/002 09:59/003 12:03/004 14:11/005 复盘，编号 001-072 跨文件连续）、
8/20 三文件、8/21 一文件——**每 raw 独立 YAML、编号按天连续递增、新 raw 永远
cp 新文件（非追加）**。核对编号 = 当日所有 YAML 最后一个 id +1（§18 同规则）。

### discover 日志命名惯例

`/tmp/discover_YYYYMMDD_N.log`（N=当日第几次），进度 `[n/N]`，完成输出
`Found N relations`。8/21：21/21、49 relations。



