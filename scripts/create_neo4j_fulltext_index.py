#!/usr/bin/env python3
"""
Create a Neo4j fulltext index on Claim nodes (subject, statement)
to accelerate keyword search in get_claims_by_keyword().

Safe to run repeatedly — uses IF NOT EXISTS.
"""
from __future__ import annotations

import sys
from pathlib import Path

from neo4j import GraphDatabase

# Add project src to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from qing_investment.agent.config import settings


def main():
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    index_name = "claim_fulltext"

    with driver.session() as session:
        # Check if index already exists
        result = session.run(
            "SHOW INDEXES YIELD name WHERE name = $name RETURN name",
            name=index_name,
        )
        existing = result.single()

        if existing:
            print(f"Fulltext index already exists: {index_name}")
        else:
            session.run(
                f"""\
CREATE FULLTEXT INDEX {index_name} IF NOT EXISTS
FOR (n:Claim)
ON EACH [n.subject, n.statement]
"""
            )
            print(f"Fulltext index created: {index_name}")

    driver.close()


if __name__ == "__main__":
    main()
