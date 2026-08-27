# 2026-07-29 Extraction Session Patterns

## Overview

4 raw files processed from 青枫浦上Q (7/29 0901早盘, 1008盘中, 1425盘中, 2205复盘). Total 36 claims extracted.

## Gate 2 False Positives Summary

Every raw file produced NON_COMPANY false positives. Pattern: 「科技」as sector descriptor dominates all categories.

### By File Type

| Raw | Claims | FP Count | Dominant Pattern |
|-----|--------|----------|-----------------|
| 0901早盘 | 14 | 3 | 科技 sector |
| 1008盘中 | 3 | 0 ✅ | — |
| 1425盘中 | 3 | 2 | 科技 sector |
| 2205复盘 | 16 | 10 | 科技 sector + 智能 + 科技有限 |

### False Positive Categories (from this session)

**Category: 科技 as sector (most common)**
New fragments added:
```
"持续放大且科技" "源是资金从科技" "一天内科技"
"可作为判断科技" "如果科技" "则可以确认科技"
"能能否回流科技" "带队只能是科技" "既参与科技"
"得最狠的是科技" "等美股科技" 
"万亿对科技" "不足以承接科技" "外绝大多数科技"
"方向只能是科技" "框架下应以科技" "仍然只能是科技"
"会随科技" "定位为科技" "是当前科技"
"费走强会随科技" "都是资金在科技" "费避险非进攻"
```

**Category: 智能 as AI descriptor**
```
"嵌入智能" "全链路智能" "以买卖家智能" "自研智能"
"作为具身智能"
```

**Category: 科技 as part of company name (月之暗面科技)**
```
"京月之暗面科技"  ← "北京月之暗面科技有限公司" is a real company, but 科技 is part of its incorporated name suffix, not a listed stock
```

### Workflow Pattern

1. Each new raw type produces 2-10 new NON_COMPANY fragments
2. Fragments must be the **exact substring** from the Gate error — not the full sentence
3. After adding to `gate_validate_claims.py`, clear cache: `rm -f temp/claims/<session>/gate2_result.json`
4. Gate 2 only reports first batch per run — expect 2-3 iterations per session

## Pipeline Notes

### run_discover_with_progress.sh Syntax Error

The shell wrapper at `scripts/run_discover_with_progress.sh` has a heredoc bug on line 27:
```
0)   REASON="正常完成" ;;
     ^
SyntaxError: closing parenthesis ')' does not match opening parenthesis '{'
```

**Workaround**: Call the Python script directly instead:
```bash
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing
```

### Multiple Raw Files in One Date

When user requests multiple dynamics from the same date, process sequentially:
1. Start separate pipeline sessions for each raw file
2. Accumulate claim IDs in chronological order
3. Do one batch git commit at the end
4. Do one sync cycle (discover→Neo4j→Qdrant) at the end

## Commit Structure

```
extract: 7/29 0901早盘→14条claims（日韩反弹/缩量见底/国产链分野/MLCC涨价/AI应用）
extract: 7/29 1008+1425盘中→6条claims（放量推仓/避险三件套/长鑫解套/半导体设备ETF）
extract: 7/29 2205复盘→16条claims（存量再分配/热钱切防御/FOMC框架/AI安全/个股定时点）
```
