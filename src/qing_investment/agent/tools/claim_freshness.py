"""
Shared claim freshness utility.

Extracted from `graph/nodes.py._apply_claim_freshness` for use across both
`/chat` and `/analyze/trigger` paths.

Labels aligned with the claim-reference hierarchy agreed on 2026-06-07:
  ≤7 days   → 最新  — current view, usable as reference
  8-30 days → 近期  — recent, diminishing value
  31-90 days→ 历史  — historical only, not for judgment
  >90 days or superseded → filtered out
"""

from datetime import datetime, date
from typing import Any


def apply_claim_freshness(claims: list[dict]) -> list[dict]:
    """Filter and annotate claims by freshness.

    Returns claims sorted by days_ago (newest first), each enriched with:
      - days_ago: int
      - freshness_label: str — one of "最新", "近期", "历史", or ""
    """
    from datetime import date as _date
    today: date = _date.today()
    filtered: list[dict] = []

    for c in claims:
        # Skip superseded
        if c.get("status") == "superseded":
            continue

        # Parse source_date
        sd = c.get("source_date", "")
        try:
            claim_date = datetime.strptime(str(sd), "%Y-%m-%d").date()
            days_ago = (today - claim_date).days
        except (ValueError, TypeError):
            days_ago = 999

        # >90 days → discard
        if days_ago > 90:
            continue

        if days_ago <= 7:
            label = "最新"
        elif days_ago <= 30:
            label = "近期"
        elif days_ago <= 90:
            label = "历史"
        else:
            label = ""

        c_copy = dict(c)
        c_copy["days_ago"] = days_ago
        c_copy["freshness_label"] = label
        filtered.append(c_copy)

    filtered.sort(key=lambda x: x.get("days_ago", 999))
    return filtered
