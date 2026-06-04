#!/usr/bin/env python3
"""
Migrate claims from knowledge/claims/*.yaml into Neo4j.

Creates:
- (:Claim) nodes
- (:Stock | :Sector | :Theme | :Macro | :Methodology) entity nodes
- (:SourceDocument) nodes
- Relationships: ABOUT, SUPERSEDES, CONTRADICTS, CITED_IN, EXTRACTED_FROM
"""
from __future__ import annotations

import glob
import os
import re
import sys
from pathlib import Path

import yaml
from neo4j import GraphDatabase

# Add project src to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from qing_investment.agent.config import settings

CLAIMS_DIR = REPO_ROOT / "knowledge" / "claims"

# Regex for Chinese stock codes (6 digits)
STOCK_CODE_RE = re.compile(r"\b(\d{6})\b")
# Regex for sector/theme keywords
SECTOR_KEYWORDS = [
    "半导体", "AI", "算力", "存储", "新能源", "光伏", "锂电", "电力", "军工",
    "商业航天", "机器人", "CPO", "光模块", "通信", "消费电子", "医药", "化工",
    "资源", "周期", "红利", "燃气轮机", "核电", "芯片", "国产替代", "数据中心",
    "光互连", "PCB", "MLCC", "ABF", "设备", "材料", "电池", "发动机",
]


def parse_claims_file(path: Path) -> list[dict]:
    """Parse a claims YAML file, handling multiple formats."""
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        print(f"  ⚠️ YAML parse error in {path.name}: {e}")
        return []
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "claims" in data:
            claims = data["claims"]
            return claims if isinstance(claims, list) else [claims]
        # Single claim dict
        return [data]
    return []


def extract_stock_codes(text: str) -> set[str]:
    return set(STOCK_CODE_RE.findall(text))


def extract_sectors(subject: str, statement: str) -> set[str]:
    """Extract sector/theme mentions from text."""
    found = set()
    combined = subject + " " + statement
    for kw in SECTOR_KEYWORDS:
        if kw in combined:
            found.add(kw)
    return found


def get_entity_type(claim_type: str, subject: str) -> str:
    """Map claim_type to entity node label."""
    mapping = {
        "stock-view": "Stock",
        "sector-theme": "Sector",
        "macro": "Macro",
        "market-cycle": "Macro",
        "methodology": "Methodology",
        "operation": "Methodology",
    }
    return mapping.get(claim_type, "Theme")


def migrate():
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    # Constraints & indexes
    with driver.session() as session:
        session.run("CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE")
        session.run("CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")
        session.run("CREATE CONSTRAINT source_path IF NOT EXISTS FOR (s:SourceDocument) REQUIRE s.path IS UNIQUE")
        session.run("CREATE INDEX claim_status IF NOT EXISTS FOR (c:Claim) ON (c.status)")
        session.run("CREATE INDEX claim_type IF NOT EXISTS FOR (c:Claim) ON (c.claim_type)")

    # Collect all claims first
    all_claims: list[dict] = []
    yaml_files = sorted(glob.glob(str(CLAIMS_DIR / "*.yaml")))
    print(f"Found {len(yaml_files)} YAML files in {CLAIMS_DIR}")

    for fp in yaml_files:
        claims = parse_claims_file(Path(fp))
        if not claims:
            print(f"  ⚠️ No claims parsed from {fp}")
            continue
        for c in claims:
            if not isinstance(c, dict):
                continue
            c["_file"] = os.path.basename(fp)
            all_claims.append(c)

    print(f"Total claims to migrate: {len(all_claims)}")

    # Batch insert claims + entities + relationships
    batch_size = 50
    with driver.session() as session:
        for i in range(0, len(all_claims), batch_size):
            batch = all_claims[i : i + batch_size]
            for claim in batch:
                _migrate_single_claim(session, claim)
            print(f"  Migrated {min(i + batch_size, len(all_claims))}/{len(all_claims)} claims")

    driver.close()
    print("✅ Claims migration complete.")


def _migrate_single_claim(session, claim: dict):
    cid = claim.get("id", "")
    if not cid:
        return

    # Merge Claim node
    session.run(
        """
        MERGE (c:Claim {id: $id})
        ON CREATE SET
            c.statement = $statement,
            c.evidence_quote = $evidence_quote,
            c.interpretation = $interpretation,
            c.confidence = $confidence,
            c.status = $status,
            c.claim_type = $claim_type,
            c.timeframe = $timeframe,
            c.subject = $subject,
            c.source_date = $source_date,
            c.source_type = $source_type,
            c.extracted_at = $extracted_at,
            c._file = $_file
        ON MATCH SET
            c.statement = $statement,
            c.evidence_quote = $evidence_quote,
            c.interpretation = $interpretation,
            c.confidence = $confidence,
            c.status = $status,
            c.claim_type = $claim_type,
            c.timeframe = $timeframe,
            c.subject = $subject,
            c.source_date = $source_date,
            c.source_type = $source_type,
            c.extracted_at = $extracted_at,
            c._file = $_file
        """,
        id=cid,
        statement=claim.get("statement", ""),
        evidence_quote=claim.get("evidence_quote", ""),
        interpretation=claim.get("interpretation", ""),
        confidence=claim.get("confidence", "medium"),
        status=claim.get("status", "active"),
        claim_type=claim.get("claim_type", "unknown"),
        timeframe=claim.get("timeframe", ""),
        subject=claim.get("subject", ""),
        source_date=claim.get("source_date", ""),
        source_type=claim.get("source_type", ""),
        extracted_at=claim.get("extracted_at", ""),
        _file=claim.get("_file", ""),
    )

    # Merge SourceDocument and link
    source_path = claim.get("source_path", "")
    if source_path:
        session.run(
            """
            MERGE (s:SourceDocument {path: $path})
            MERGE (c:Claim {id: $cid})
            MERGE (c)-[:EXTRACTED_FROM]->(s)
            """,
            path=source_path,
            cid=cid,
        )

    # Create entity relationships (ABOUT)
    subject = claim.get("subject", "")
    statement = claim.get("statement", "")
    claim_type = claim.get("claim_type", "unknown")
    entity_label = get_entity_type(claim_type, subject)

    # Subject as primary entity
    if subject:
        session.run(
            f"""
            MERGE (e:{entity_label} {{name: $name}})
            MERGE (c:Claim {{id: $cid}})
            MERGE (c)-[:ABOUT {{relation_type: 'primary'}}]->(e)
            """,
            name=subject,
            cid=cid,
        )

    # Stock codes from statement
    codes = extract_stock_codes(statement + " " + claim.get("evidence_quote", ""))
    for code in codes:
        session.run(
            """
            MERGE (s:Stock {code: $code})
            MERGE (c:Claim {id: $cid})
            MERGE (c)-[:ABOUT {relation_type: 'mentions'}]->(s)
            """,
            code=code,
            cid=cid,
        )

    # Sector keywords
    sectors = extract_sectors(subject, statement)
    for sector in sectors:
        session.run(
            """
            MERGE (sec:Sector {name: $name})
            MERGE (c:Claim {id: $cid})
            MERGE (c)-[:ABOUT {relation_type: 'sector'}]->(sec)
            """,
            name=sector,
            cid=cid,
        )

    # Wiki page links -> CITED_IN
    links = claim.get("links", {}) or {}
    wiki_pages = links.get("wiki_pages", []) if isinstance(links, dict) else []
    for wp in wiki_pages:
        session.run(
            """
            MERGE (w:WikiPage {path: $path})
            MERGE (c:Claim {id: $cid})
            MERGE (c)-[:CITED_IN]->(w)
            """,
            path=wp,
            cid=cid,
        )

    # Methodology page links
    meth_pages = links.get("methodology_pages", []) if isinstance(links, dict) else []
    for mp in meth_pages:
        session.run(
            """
            MERGE (m:MethodologyPage {path: $path})
            MERGE (c:Claim {id: $cid})
            MERGE (c)-[:CITED_IN]->(m)
            """,
            path=mp,
            cid=cid,
        )

    # Deferred relationships: we need a second pass for SUPERSEDES / CONTRADICTS


def migrate_relations():
    """Second pass: create SUPERSEDES and CONTRADICTS relationships."""
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    all_claims: list[dict] = []
    yaml_files = sorted(glob.glob(str(CLAIMS_DIR / "*.yaml")))
    for fp in yaml_files:
        claims = parse_claims_file(Path(fp))
        for c in claims:
            if isinstance(c, dict):
                all_claims.append(c)

    with driver.session() as session:
        for claim in all_claims:
            cid = claim.get("id", "")
            if not cid:
                continue

            supersedes = claim.get("supersedes", []) or []
            for old_id in supersedes:
                session.run(
                    """
                    MATCH (new:Claim {id: $new_id}), (old:Claim {id: $old_id})
                    MERGE (new)-[:SUPERSEDES]->(old)
                    """,
                    new_id=cid,
                    old_id=old_id,
                )

            contradicts = claim.get("contradicts", []) or []
            for opp_id in contradicts:
                session.run(
                    """
                    MATCH (a:Claim {id: $a_id}), (b:Claim {id: $b_id})
                    MERGE (a)-[:CONTRADICTS]->(b)
                    """,
                    a_id=cid,
                    b_id=opp_id,
                )

    driver.close()
    print("✅ Relations migration (SUPERSEDES/CONTRADICTS) complete.")


if __name__ == "__main__":
    migrate()
    migrate_relations()
