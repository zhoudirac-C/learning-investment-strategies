#!/usr/bin/env python3
"""Migrate Neo4j claims into Qdrant for semantic search."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from qing_investment.agent.tools.llm_client import get_embedding_model
from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.config import settings

COLLECTION = "qing_claims"
VECTOR_DIM = 512
QDRANT_BASE = f"http://{settings.qdrant_host}:{settings.qdrant_port}"


def ensure_collection():
    resp = requests.get(f"{QDRANT_BASE}/collections")
    collections = [c["name"] for c in resp.json().get("result", {}).get("collections", [])]
    if COLLECTION not in collections:
        r = requests.put(
            f"{QDRANT_BASE}/collections/{COLLECTION}",
            json={"vectors": {"size": VECTOR_DIM, "distance": "Cosine"}}
        )
        print(f"Created collection {COLLECTION}: {r.status_code}")


def upsert_points(points: list):
    r = requests.put(
        f"{QDRANT_BASE}/collections/{COLLECTION}/points",
        json={"points": points}
    )
    r.raise_for_status()


def main():
    neo4j = Neo4jClient()
    emb_model = get_embedding_model()
    ensure_collection()

    with neo4j.driver.session() as session:
        result = session.run(
            "MATCH (c:Claim) RETURN c.id as id, c.statement as statement, "
            "c.subject as subject, c.source_date as source_date, "
            "c.confidence as confidence, c.status as status"
        )
        claims = list(result)

    print(f"Found {len(claims)} claims in Neo4j")

    batch = []
    total = 0
    batch_size = 50

    for claim in claims:
        cid = claim["id"]
        text = f"{claim.get('subject', '')} | {claim.get('statement', '')}"
        emb = emb_model.encode(text).tolist()[0]

        # Neo4j 可能返回 Date 对象，需要转字符串
        sd = claim.get("source_date", "")
        if hasattr(sd, "iso_format"):
            sd = sd.iso_format()
        elif hasattr(sd, "isoformat"):
            sd = sd.isoformat()
        else:
            sd = str(sd) if sd else ""

        point_id = hashlib.sha256(cid.encode("utf-8")).hexdigest()[:32]
        batch.append({
            "id": point_id,
            "vector": emb,
            "payload": {
                "claim_id": cid,
                "statement": claim.get("statement", ""),
                "subject": claim.get("subject", ""),
                "source_date": sd,
                "confidence": claim.get("confidence", ""),
                "status": claim.get("status", ""),
            },
        })

        if len(batch) >= batch_size:
            upsert_points(batch)
            total += len(batch)
            print(f"  Indexed {total}/{len(claims)} claims")
            batch = []

    if batch:
        upsert_points(batch)
        total += len(batch)

    neo4j.close()
    print(f"✅ Indexed {total} claims into Qdrant collection '{COLLECTION}'")


if __name__ == "__main__":
    main()
