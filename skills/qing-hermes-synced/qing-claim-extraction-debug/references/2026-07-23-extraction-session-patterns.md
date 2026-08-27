# 2026-07-23/24 Claim Extraction Session — Real-World Patterns

## Overview

Over two sessions extracted 37 + 12 = 49 claims from 5 bilibili dynamics.

### Session 1 (7/23): 25 claims from 4 dynamics
- 0957 (谷歌云/capex), 1122 (行情不V), 1331 (华虹+下半年), 2151 (晚间复盘)

### Session 2 (7/24): 12 claims from 1 dynamic
- 0858 (早盘：缩量普涨做减法, 2.5万亿安全区间)

---

## Session 1: 2151 Evening Review — NON_COMPANY additions

The 2151 file was a long-form evening review (~300 lines) with detailed
sector analysis, stock commentary, and forward-looking framework. Its
interpretation fields contained many sector-level references that Gate 2
correctly flagged (but are not actual company names).

### Fragments added to NON_COMPANY

```python
# "有限" in opinion/context (not company suffix)
"暗示空间有限",     # "新能源虽可高看一眼但需注意压力位，暗示空间有限"

# "科技" as sector/plate reference (12+ hits across multiple claims)
"看空科技",         # "原油对科技是利空" — analysis, not a company
"上市是近期科技",   # "长鑫上市是近期科技催化剂"
"放缓是当前科技",   # "CAPEX放缓是当前科技板块的压制因素"

# "智能" as AI domain (not company)
"北京市加快智能",   # City name + policy domain
"提出夯实智能",     # Policy wording
"芯片的通用智能",   # "跨模型跨芯片的通用智能体技术攻关"

# "电子" as subsidiary (unlisted, covered by parent's related_stocks)
"金胜电子",         # Owned by 恒尚节能(603137), not listed
"收购的金胜电子",   # Same — covered by parent company's related_stocks entry
```

### Pattern observed

Long-form evening reviews generate the most NON_COMPANY false positives
because interpretation paragraphs contain:
- Sector/plate analysis (科技/电子/智能 as domain references)
- Conditional phrasing (空间有限 as opinion qualifier, not company suffix)
- Subsidiary names (金胜电子 as M&A target, not listed entity)

### Pre-emptive avoidance strategy

Before running Gate 2 on a long-form review, scan interpretation fields for:
```
[2-5汉字] + (科技|电子|智能|有限)
```
Batch-add all matches to NON_COMPANY in one go to save a round-trip.

---

## Session 1: 1331 Mixed-Content Post — 寓言包裹Structured Content

Post 1331 was mostly psychological/寓言 (换了问法失望, 亏钱两种结局)
but contained 3 structured claims embedded within the motivational framing:

1. **华虹半导体20日线** (technical-signal) — 5日/10日线过拟合看20日线
2. **下半年难度超上半年** (market-cycle) — 指数涨但操作更难
3. **技术派vs情绪派分化** (methodology) — 市场参与者分野

**Extraction rule for mixed posts**: Do NOT skip the entire post just because
the first 60% is 寓言/心理按摩. Read to the end — structured content often
appears in the final paragraphs after the motivational buildup.

### How to identify extractable content in mixed posts

| Signal | Example from 1331 |
|--------|------------------|
| Specific stock + technical level | 华虹半导体20日线 |
| Verifiable market judgment | 下半年难度超上半年 |
| Observable market phenomenon | 技术派和情绪派出现 |
| Skip signal (no extraction) | 换了问法、亏钱抱怨、人形量化对决 |

---

## Session 2: 7/24 0858 Early Morning Report — NON_COMPANY additions

The 0858 file was a long-form early morning report (~90 lines of analysis)
with sector analysis, policy interpretation, and multiple industry tracking
lines. Same pattern as evening reviews — interpretation fields trigger false
positives.

### New fragments added

```python
# "科技" as sector/plate (3 new contexts)
"更新科技",         # "更新科技磨底时间预期" — judgment about sector
"率先企稳的科技",   # "筛选可能率先企稳的科技细分" — strategy description
"涨幅有限的科技",   # "寻找涨幅有限的科技细分" — selection criteria

# "科技" with geographic/industry qualifier
"北美科技",         # "北美科技巨头资本开支上修" — reference to US tech companies

# "智能" in policy context
"加快智能",         # "北京印发《加快智能体引领发展若干措施》" — policy title fragment

# "有限" in selection criterion (not company suffix)
"涨幅有限",         # "涨幅有限的科技细分方向" — filter description
```

### Key difference from Session 1

Session 2's false positives came from **policy interpretation** and **strategy
filter criteria**, not from analysis of specific stocks or sectors. The
interpretation fields for Catalyst-type claims (Token经济政策, AI电力, 脑机接口)
produced these.

### Prediction for future sessions

Early morning reports (0858 style) and evening reviews (2151 style) will
**always** generate NON_COMPANY false positives because their interpretation
patterns are structurally similar — long descriptive paragraphs about sectors,
policies, and strategy criteria rather than short, stock-specific analysis.

### Gate cache deletion: quick reference

After adding to NON_COMPANY:
```bash
# Delete Gate 2 cache before re-running
rm -f temp/claims/<session_id>/gate2_result.json

# Re-run validation
python scripts/extract_claims_pipeline.py continue <session_id>
```

If Gate 1 cache is stale (you modified step1_raw.json but `continue` still
reports the same Gate 1 errors):
```bash
rm -f temp/claims/<session_id>/gate1_result.json
python scripts/extract_claims_pipeline.py continue <session_id>
```
