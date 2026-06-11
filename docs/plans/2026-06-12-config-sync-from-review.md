# Config Sync from Daily Review — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement task-by-task.

**Goal:** After the 17:00 daily review Agent generates its analysis, automatically write back structured fields to `strategy_pack.yaml`, `positions.yaml`, and `watchlist.yaml`, so poll and agents operate on current data the next day.

**Architecture:** Two-part change:
1. Update 17:00 cron prompt to ask LLM to output additional fields in its `daily_state` JSON block
2. Create a new sync script that reads the 17:00 cron output, extracts the `daily_state` block, and writes fields to config YAML files

**Tech Stack:** Python, PyYAML, re, Pathlib. No new dependencies.

---

## Field Mapping

### From existing daily_state fields (no prompt change needed)

| daily_state field | → Target file | → Target path |
|---|---|---|
| `market_stage.phase` | `strategy_pack.yaml` | `market_framework.current_stage` |
| `market_stage.detail` | `strategy_pack.yaml` | `market_framework.current_stage` (append) |
| `direction_priority` | `strategy_pack.yaml` | `sector_rotation_rules` (direction_priority field) |
| `position_stance` | `positions.yaml` | `strategy_summary.current_stage` |

### Need to add to daily_state (update 17:00 prompt)

| New field in daily_state | → Target file | → Target path |
|---|---|---|
| `risk_reminder` | `positions.yaml` | `risk_reminder` |
| `today_key_signals[]` | `positions.yaml` | `today_key_signals` |
| `tomorrow_scenarios` | `positions.yaml` | `tomorrow_scenarios` |
| `entry_zone_updates[{code, current_ref}]` | `watchlist.yaml` | per-stock `entry_zone.current_ref` |

---

## Tasks

### Task 1: Read current 17:00 daily review prompt

**Objective:** Understand the current prompt structure and where to inject the output format requirement.

**Files:**
- Find: `~/.hermes/cron/output/fc7d8a270d84/` — the cron job's prompt template is stored in the cron DB
- Read: the daily review files to understand existing daily_state JSON format

**Verification:** `cronjob(action='list')` — confirm the prompt preview matches our understanding.

---

### Task 2: Update 17:00 cron prompt to include output format requirements

**Objective:** Add structured JSON output fields to the 17:00 daily review prompt.

**Files:**
- Modify: 17:00 cron job (`fc7d8a270d84`) prompt via `cronjob(action='update')`

**Changes to prompt:** Add after existing prompt text:

```
【输出格式要求】
在分析结尾输出 daily_state JSON 代码块，包含以下字段（除已有字段外新增）：

```daily_state
{
  "risk_reminder": "止损纪律仍然有效（雅克123.2/风华60.9）。...",
  "today_key_signals": ["全A收盘X点，涨跌X%", "...", "..."],
  "tomorrow_scenarios": {
    "strong_repair": {"probability": "30%"},
    "weak_consolidation": {"probability": "50%"}
  },
  "entry_zone_updates": [
    {"code": "600378", "name": "昊华科技", "current_ref": "2026-06-12 收盘=XX"},
    {"code": "601012", "name": "隆基绿能", "current_ref": "..."},
    {"code": "000657", "name": "中钨高新", "current_ref": "..."}
  ],
  "market_stage": {"phase": "...", "detail": "..."},
  "direction_priority": [{"direction": "...", "intensity": "..."}],
  "position_stance": "..."
}
```
```

**Verification:** `cronjob(action='list')` — prompt preview contains `risk_reminder` and `entry_zone_updates`.

---

### Task 3: Create sync_config_from_review.py

**Objective:** Script that reads latest 17:00 cron output, extracts daily_state JSON, and writes updates to config YAML files.

**Files:**
- Create: `scripts/sync_config_from_review.py` (~200 lines)

**Key design:**
```python
def sync_config():
    # 1. Find latest output for 17:00 cron (fc7d8a270d84)
    # 2. Extract ```daily_state JSON block
    # 3. Read strategy_pack.yaml, positions.yaml, watchlist.yaml
    # 4. Apply field mapping:
    #    - market_stage.phase → strategy_pack.market_framework.current_stage
    #    - position_stance → positions.strategy_summary.current_stage
    #    - risk_reminder → positions.risk_reminder
    #    - today_key_signals → positions.today_key_signals
    #    - tomorrow_scenarios → positions.tomorrow_scenarios
    #    - entry_zone_updates → watchlist.yaml per-stock current_ref
    # 5. Write updated YAML files
    # 6. Log changes
```

**YAML handling:**
- Use `yaml.safe_load()` + patch individual fields (not full rewrite)
- For positions.yaml: load → modify → write (it's gitignored, safe to write)
- For watchlist.yaml: find matching stock by code, update entry_zone.current_ref
- For strategy_pack.yaml: update market_framework.current_stage

**Edge cases:**
- No daily_state block found → exit with warning, no changes
- daily_state missing optional fields → skip that field, don't fail
- Watchlist stock code not found → log warning, skip

**Verification:** 
```bash
PYTHONPATH=src python3 scripts/sync_config_from_review.py --dry-run
```

---

### Task 4: Register sync cron job at 17:05

**Objective:** Run the new script 5 min after daily review completes.

**Files:**
- Create: `~/.hermes/scripts/qing_sync_config_from_review.sh`
- Register: `cronjob(action='create')`

**Cron config:**
- Schedule: `5 17 * * 1-5` (weekdays at 17:05)
- Script: `qing_sync_config_from_review.sh`
- no_agent: true
- workdir: project root
- deliver: local (no need to notify user, changes are silent)

**Verification:**
```bash
hermes cron run <new_job_id>
# Check: strategy_pack.yaml updated_at updated
# Check: positions.yaml risk_reminder updated
```

---

## Files Modified

| Action | File |
|---|---|
| Update | Cron prompt for job_id=`fc7d8a270d84` (17:00 daily review) |
| Create | `scripts/sync_config_from_review.py` |
| Create | `~/.hermes/scripts/qing_sync_config_from_review.sh` |
| Create | Cron job (17:05, no-agent) |

## Verification

- [ ] 17:00 prompt preview contains `risk_reminder`, `entry_zone_updates`, `today_key_signals`
- [ ] `sync_config_from_review.py --dry-run` prints correct changes without writing
- [ ] After run: `strategy_pack.yaml` `current_stage` matches Agent output
- [ ] After run: `positions.yaml` `today_key_signals` has 3-5 items
- [ ] After run: `watchlist.yaml` current_ref for key stocks updated
- [ ] Cron job registered and executable
