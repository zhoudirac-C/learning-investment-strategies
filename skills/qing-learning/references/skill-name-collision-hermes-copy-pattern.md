# Skill Name Collision: Hermes Copy Pattern

## Problem

When a skill exists in both `~/.hermes/skills/` (Hermes global) and `~/learning-investment-strategies/skills/` (project repo), `skill_view()` reports ambiguity and refuses to load.

Example:
```
Ambiguous skill name 'qing-event-pipeline': 2 skills match across your
local skills dir and external_dirs. Refusing to guess.
```

## Root Cause

Hermes scans both `~/.hermes/skills/` and `external_dirs` (e.g. `~/learning-investment-strategies/skills/`) for skill discovery. When the same skill name exists in both locations, the resolver cannot determine which to load.

## Solution

Rename the **Hermes global copy** to `<name>-hermes-copy`. The **project repo version** is the primary source of truth.

### Steps

```bash
# 1. Rename the Hermes global copy
cd ~/.hermes/skills/
mv qing-event-pipeline qing-event-pipeline-hermes-copy

# 2. Verify project version is still intact
ls ~/learning-investment-strategies/skills/qing-event-pipeline/

# 3. Verify Hermes can now load the project version unambiguously
hermes skills list | grep qing-event
```

## Existing Hermes Copies (as of 2026-06-10)

| Original Name | Hermes Copy Name | Status |
|---------------|-----------------|--------|
| `qing-learning-claim` | `qing-learning-claim-hermes-copy` | ✅ Renamed |
| `qing-learning-ingestion` | `qing-learning-ingestion-hermes-copy` | ✅ Renamed |
| `qing-learning-review` | `qing-learning-review-hermes-copy` | ✅ Renamed |
| `qing-learning-sync` | `qing-learning-sync-hermes-copy` | ✅ Renamed |
| `qing-event-pipeline` | `qing-event-pipeline-hermes-copy` | ⚠️ Needs rename |

## When to Create a Hermes Copy vs. Project-Only

| Scenario | Action |
|----------|--------|
| Skill is project-specific (e.g. `qing-event-pipeline`) | Keep in project repo only; create `-hermes-copy` if accidentally copied to global |
| Skill is generic (e.g. `hermes-agent`) | Keep in Hermes global only |
| Skill needs to be available in both contexts | Keep primary in project repo; symlink or copy to global with `-hermes-copy` suffix |

## Prevention

When copying a skill from project repo to Hermes global (e.g. for testing), always rename it immediately:

```bash
cp -r ~/learning-investment-strategies/skills/my-skill ~/.hermes/skills/my-skill-hermes-copy
```

Or better: don't copy at all. Use `external_dirs` in `~/.hermes/config.yaml` to let Hermes discover project skills directly.
