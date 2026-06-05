#!/usr/bin/env python3
"""Incrementally sync claims from Neo4j to Qdrant (qing_claims collection) for semantic search."""

import hashlib
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.tools.llm_client import get_embedding_model
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper
from qdrant_client.models import PointStruct

COLLECTION = "qing_claims"
VECTOR_DIM = 512


def main():
    neo4j = Neo4jClient()
    qdrant = QdrantClientWrapper(local_mode=True)
    emb_model = get_embedding_model()

    qdrant.ensure_collection(COLLECTION, vector_size=VECTOR_DIM)

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
        emb = emb_model.encode(text).tolist()

        sd = claim.get("source_date", "")
        if hasattr(sd, "iso_format"):
            sd = sd.iso_format()
        elif hasattr(sd, "isoformat"):
            sd = sd.isoformat()
        else:
            sd = str(sd) if sd else ""

        point_id = hashlib.sha256(cid.encode("utf-8")).hexdigest()[:32]
        batch.append(PointStruct(
            id=point_id,
            vector=emb,
            payload={
                "claim_id": cid,
                "statement": claim.get("statement", ""),
                "subject": claim.get("subject", ""),
                "source_date": sd,
                "confidence": claim.get("confidence", ""),
                "status": claim.get("status", ""),
            },
        ))

        if len(batch) >= batch_size:
            qdrant.upsert(COLLECTION, batch)
            total += len(batch)
            print(f"  Indexed {total}/{len(claims)} claims")
            batch = []

    if batch:
        qdrant.upsert(COLLECTION, batch)
        total += len(batch)

    neo4j.close()
    print(f"✅ Indexed {total} claims into Qdrant collection '{COLLECTION}'")


if __name__ == "__main__":
    main()
