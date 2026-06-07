# Claim Topic & Tag Auto-Generation

> Script: `scripts/add_topics_tags.py`  
> Purpose: Auto-generate `topic` and `tags` fields for claims that lack them

## When to use

- Batch backfilling `topic`/`tags` on old-format claim files
- Claims migrated from pre-schema era that only have `subject`/`statement` but no `topic`/`tags`
- Use as a reference for how rule-based Chinese topic/tag extraction works (keyword matching, clause splitting, dedup)

## How it works

### Topic generation

1. If `subject` is concise (5-20 chars) and specific (not in GENERIC_SUBJECTS list), use it directly
2. Otherwise, extract the first meaningful clause from `statement` (split by Chinese delimiters `，。！？；\n`)
3. Fall back to combining subject + first clause if needed

Examples:
- `subject="长鑫存储产业链"` → topic=`长鑫存储产业链` (subject is good)
- `subject="市场情绪"` + `statement="空方力量已出现明显衰竭..."` → topic=`空方力量已出现明显衰竭` (generic subject → use statement)
- `subject="蒙代尔不可能三角与政策选择"` → topic=`蒙代尔不可能三角与政策选择` (subject is specific)

### Tag generation

1. Always include the `claim_type` category (e.g., "宏观", "市场周期")
2. Extract sector/stock keywords from a curated list of 100+ Chinese finance terms
3. Extract stock names via whitelist matching (no regex to avoid false positives)
4. Extract technical terms from statement (e.g., "顶部结构", "情绪拐点", "空头回补")
5. Pad to minimum 3 tags, trim to maximum 8
6. Deduplicate substrings ("上证" is removed when "上证指数" is present)

## File format handling

The script handles three YAML claim file formats:

| Format | Example | Detection |
|--------|---------|-----------|
| `claims:` wrapper | `claims:\n  - id: claim-xxx` | First line starts with `claims:` |
| Bare list | `- id: claim-xxx` | First line starts with `- id:` |
| Single dict | `id: claim-xxx` | First line starts with `id:` |

Fields are written back preserving the original indentation:
- Wrapper: 4-space indent for fields
- Bare list: 2-space indent for fields
- Single dict: 0-space indent (root level)

## Pitfalls discovered

1. **Stock name regex produces false positives**: Regex like `[\u4e00-\u9fff]{2,4}(?:科技|电子|...)` matches substrings (e.g., "游设备和材料" from "上游设备和材料"). **Fix**: Use a whitelist of known stock names instead.

2. **Keyword dedup must prefer longer matches**: Sorting by length descending prevents "上证" from surviving when "上证指数" is also found. But dedup must also run after the minimum-3 padding step — otherwise claims like 劣性轮动 can end up with only 2 tags after dedup removes "轮动".

3. **Single-dict format requires special handling**: Files like `claim-20260524-001.yaml` use `id:` at root level (not `- id:`). These must be detected via the first line (`"id:"`) and written back with 0-space indent.

4. **"上证指数" must be in the keyword list, not just "上证"**: Without explicit inclusion, claims about 上证指数 only get "上证" as a tag, which then gets expanded to "上证指数" via the padding step — but the quality is worse.

5. **Generic subjects degrade topic quality**: Subjects like "市场情绪", "操作策略", "大盘" are too generic. Extract from `statement` instead.
