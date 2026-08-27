# Batch Extraction Workflow — Multi-File Pipeline Execution

## When to use

When UP posts multiple bilibili dynamics in one day (common pattern: 5-6 dynamics
ranging from 0957 early morning through 2151 evening review). Running the pipeline
for each file serially wastes round-trips on repeated gate validation.

## Optimal workflow

### Phase 1: Read and copy all files

```
1.  grep -l "unprocessed: true" sources/original/bilibili/YYYY-MM-DD*.md
2.  For each file, read the content (tail -n +12 to skip frontmatter)
3.  Evaluate each file:
    - Has structured content (stocks, prices, judgments)? → Extract
    - Pure 寓言/心理按摩/仅附图? → Skip (mark unprocessed: false)
    - Video without transcript? → Skip (mark unprocessed, note for later)
4.  Copy extractable files to sources/raw/财经/ with clean filenames
```

### Phase 2: Start all pipelines

```
# Start ALL pipelines at once (they just create sessions)
python scripts/extract_claims_pipeline.py start --raw sources/raw/财经/file1.md
python scripts/extract_claims_pipeline.py start --raw sources/raw/财经/file2.md
...
```

### Phase 3: Process in batch

Process files in order of value (longest/most valuable first):

```
# For each file, write step1_raw.json (all 18 fields, NO related_stocks/tags)
# Run Gate 1:
python scripts/extract_claims_pipeline.py continue <session_id>

# If Gate 1 fails → fix step1, delete gate1_result.json, re-run continue
# If Gate 1 passes → write step2_enriched.json (add codes, related_stocks, tags)

# Run Gate 2:
python scripts/extract_claims_pipeline.py continue <session_id>

# If Gate 2 fails (NON_COMPANY false positives):
#   1. Read errors, classify each fragment
#   2. Add to gate_validate_claims.py NON_COMPANY set
#   3. Delete gate2_result.json cache
#   4. Re-run continue

# If Gate 2 passes → run continue for auto YAML (Step 3)
python scripts/extract_claims_pipeline.py continue <session_id>
```

### Phase 4: Consolidate YAML output

```
# For each file:
cp temp/claims/<session_id>/step3_yaml/claim-*-output.yaml knowledge/claims/claim-YYYYMMDD-NNN.yaml
rm temp/claims/<session_id>/step3_yaml/claim-*-output.yaml
python scripts/extract_claims_pipeline.py done <session_id>
```

### Phase 5: Update indexes and commit once

```
# Update claims/index.md (append all new files)
# Update wiki (create daily review, add to wiki/index.md, update log)
# Mark original files as unprocessed: false
# Clean up sources/raw/财经/ temp files
# git add -A && git commit (single commit for all files)
```

## Cumulative NON_COMPANY growth pattern

Each file in a batch will likely add new NON_COMPANY patterns as the
interpreter encounters new contexts. The additions are monotonic — by
the time you process the 3rd or 4th file in a batch, Gate 2 failures
should become rarer because most common patterns are already covered.

Expected additions per file (based on 7/23-24 session):

| File type | Expected new NON_COMPANY | Examples |
|-----------|-------------------------|----------|
| 早盘 (market cycle) | 3-5 (主营/科技/有限) | "放缓是当前科技", "涨幅有限" |
| 晚间复盘 (structured) | 5-10 (科技/智能/电子/有限/子公司) | "金胜电子", "暗示空间有限" |
| 短动态 (<5 lines) | 0-1 | Typically clean |
| 产业新闻 (catalyst) | 2-4 (智能/科技 in policy contexts) | "北京市加快智能" |
