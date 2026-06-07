#!/usr/bin/env python3
"""
Backfill name property on Stock nodes that lack it.

For each Stock node without a name (or with an empty name), finds the
associated Claim nodes via any ABOUT relationship and extracts the most
frequent subject as the stock name.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from neo4j import GraphDatabase
from qing_investment.agent.config import settings


def _load_code_to_name_mapping() -> dict[str, str]:
    """Build code -> name mapping from positions.yaml (name_to_code reversed)."""
    mapping: dict[str, str] = {}
    try:
        positions_path = REPO_ROOT / "config" / "stock_monitor" / "positions.yaml"
        if positions_path.exists():
            import yaml

            data = yaml.safe_load(positions_path.read_text(encoding="utf-8"))
            for account in data.get("accounts", []):
                for pos in account.get("positions", []):
                    name = pos.get("name", "")
                    code = (
                        pos.get("code", "")
                        .replace(".SZ", "")
                        .replace(".SH", "")
                        .replace(".sz", "")
                        .replace(".sh", "")
                    )
                    if name and code:
                        mapping[code] = name
    except Exception:
        pass
    return mapping


def backfill_stock_names(driver) -> int:
    """Set name on Stock nodes that don't have one. Returns count of nodes updated."""
    code_to_name = _load_code_to_name_mapping()

    with driver.session() as session:
        # 1. Find Stock nodes without a name
        result = session.run(
            """
            MATCH (s:Stock)
            WHERE s.name IS NULL OR s.name = ''
            RETURN s.code AS code
            """
        )
        nodenames = [r["code"] for r in result]
        if not nodenames:
            print("✅ All Stock nodes already have a name.")
            return 0

        print(f"Found {len(nodenames)} Stock nodes without a name.")

        updated = 0
        for code in nodenames:
            # Priority 1: positions.yaml mapping (most accurate)
            if code in code_to_name:
                session.run(
                    "MATCH (s:Stock {code: $code}) SET s.name = $name",
                    {"code": code, "name": code_to_name[code]},
                )
                print(f"  ✅ {code} → name={code_to_name[code]} [from positions.yaml]")
                updated += 1
                continue

            # Priority 2: Find connected Claim nodes and use most frequent subject
            subjects = session.run(
                """
                MATCH (c:Claim)-[:ABOUT]->(s:Stock {code: $code})
                WHERE c.subject IS NOT NULL AND c.subject <> ''
                RETURN c.subject AS subject
                """,
                {"code": code},
            ).values()

            if subjects:
                flat_subjects = [s[0] for s in subjects if s and s[0]]
                if flat_subjects:
                    most_common = Counter(flat_subjects).most_common(1)[0][0]
                    session.run(
                        "MATCH (s:Stock {code: $code}) SET s.name = $name",
                        {"code": code, "name": most_common},
                    )
                    print(f"  ✅ {code} → name={most_common} [from claims]")
                    updated += 1
                    continue

            # Priority 3: Use code as placeholder
            session.run(
                "MATCH (s:Stock {code: $code}) SET s.name = $name",
                {"code": code, "name": code},
            )
            print(f"  ⚠️  {code} → name=code ({code}) [no data found]")
            updated += 1

        return updated


def main():
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        total = backfill_stock_names(driver)
        print(f"\n✅ Backfill complete: {total} Stock nodes updated.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
