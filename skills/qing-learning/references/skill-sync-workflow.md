# Skill Synchronization Workflow

## Context

The qing-learning project maintains its own skill library under `~/learning-investment-strategies/skills/`. These are the **primary source of truth**. A secondary copy may exist in the Hermes global skill directory (`~/.hermes/skills/` via symlinks or duplicates).

When the global copies drift from the project copies, or when setting up a new environment, follow this workflow to consolidate.

## Consolidation Steps

### 1. Compare Line Counts

```bash
wc -l ~/learning-investment-strategies/skills/*/SKILL.md
wc -l ~/.hermes/skills/*/SKILL.md   # if any exist
```

If project skills are significantly smaller than global copies, the global copies have content that needs to be merged down.

### 2. Merge Global Content into Project Skills

For each skill that needs updating:
- Read the global SKILL.md (source of richer content)
- Read the project SKILL.md (source of project-specific paths and conventions)
- Merge: keep project-specific paths (e.g., `~/learning-investment-strategies/...`), append global content sections that are missing

### 3. Update Hermes Config

Edit `~/.hermes/config.yaml` to point `skills.external_dirs` to the project directory:

```yaml
skills:
  external_dirs:
  - ~/.agents/skills
  - ~/learning-investment-strategies/skills
```

### 4. Remove Global Skill Copies

After confirming Hermes loads skills from the project directory:

```bash
# List skills Hermes can see
hermes skills list

# Remove global copies that are now duplicated
rm -rf ~/.hermes/skills/finance-research-report/qing-stock-analysis
rm -rf ~/.hermes/skills/finance-research-report/qing-stock-monitor-update
rm -rf ~/.hermes/skills/investment-research/qing-learning
rm -rf ~/.hermes/skills/investment-research/qing-methodology-review
```

### 5. Verify

```bash
hermes skills list | grep qing-
```

All four skills should show `local` source, not `global`.

## User Preference

When the user asks to "update skills" without specifying location, they mean the **project repo version** (`~/learning-investment-strategies/skills/`), not the Hermes global copy. Always clarify if ambiguous.
