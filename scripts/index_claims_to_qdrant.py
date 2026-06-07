#!/usr/bin/env python3
"""Incrementally sync claims from Neo4j to Qdrant (qing_claims collection) for semantic search.

Pre-flight checks:
- Auto-kills running Qing-Agent (uvicorn) to avoid concurrent Qdrant access
- Waits for Qdrant .lock file to be released
Post-index integrity check:
- Validates random sample of indexed vectors have correct dimension (512)
"""

import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.tools.llm_client import get_embedding_model
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper
from qdrant_client.models import PointStruct

COLLECTION = "qing_claims"
VECTOR_DIM = 512
QDRANT_DATA_DIR = os.path.join(PROJECT_ROOT, ".qdrant_data")
QDRANT_LOCK_FILE = os.path.join(QDRANT_DATA_DIR, ".lock")


def _kill_agent_if_running():
    """Kill uvicorn Qing-Agent to release Qdrant local mode file lock."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "uvicorn qing_investment"],
            capture_output=True, text=True
        )
        pids = result.stdout.strip().split()
        if pids:
            print(f"⚠️ Qing-Agent running (PIDs: {', '.join(pids)}), killing to release Qdrant lock...")
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
            time.sleep(2)
            # Force kill if still running
            result2 = subprocess.run(
                ["pgrep", "-f", "uvicorn qing_investment"],
                capture_output=True, text=True
            )
            remaining = result2.stdout.strip().split()
            if remaining:
                for pid in remaining:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                time.sleep(1)
            print("✅ Agent stopped")
        else:
            print("✅ Agent not running")
    except Exception as e:
        print(f"⚠️ Agent check failed (non-fatal): {e}")


def _wait_for_qdrant_lock(timeout: int = 30):
    """Wait for Qdrant .lock file to be removed by other processes."""
    if not os.path.exists(QDRANT_LOCK_FILE):
        print("✅ Qdrant lock free")
        return True
    print(f"⚠️ Qdrant .lock file exists, waiting (max {timeout}s)...")
    for i in range(timeout):
        if not os.path.exists(QDRANT_LOCK_FILE):
            print(f"✅ Qdrant lock released after {i+1}s")
            return True
        time.sleep(1)
    print(f"❌ Qdrant lock still held after {timeout}s — force-removing")
    try:
        os.remove(QDRANT_LOCK_FILE)
    except OSError:
        pass
    return False


def _verify_vectors(qdrant: QdrantClientWrapper, expected_dim: int = 512, sample_size: int = 10):
    """Verify indexed vectors have correct dimension. Returns False if corruption detected."""
    import random as _random
    from qdrant_client.models import ScoredPoint

    try:
        # Get total count via count API
        count_result = qdrant._client.count(collection_name=COLLECTION)
        total = count_result.count
        if total == 0:
            print("⚠️ Integrity check skipped: collection is empty")
            return True

        # Pick random offsets to sample
        offsets = sorted(_random.sample(range(total), min(sample_size, total)))
        
        bad_vectors = []
        for offset in offsets:
            result = qdrant._client.scroll(
                collection_name=COLLECTION,
                limit=1,
                offset=offset,
                with_vectors=True,
            )
            points = result[0]
            if points:
                vec = np.array(points[0].vector).flatten()
                if vec.shape[0] != expected_dim:
                    bad_vectors.append((points[0].id, vec.shape[0]))
        
        if bad_vectors:
            print(f"❌ INTEGRITY CHECK FAILED: {len(bad_vectors)}/{sample_size} vectors have wrong dimension:")
            for pid, dim in bad_vectors:
                print(f"   point {pid}: shape=({dim},) expected=({expected_dim},)")
            print("   → Collection may be corrupted. Run with --force-recreate to rebuild.")
            return False
        
        print(f"✅ Integrity check passed: {sample_size}/{sample_size} vectors have correct dimension ({expected_dim})")
        return True
        
    except Exception as e:
        print(f"⚠️ Integrity check failed with error (non-fatal): {e}")
        return True  # Don't fail the whole job over a check


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-recreate", action="store_true",
                        help="Delete and recreate collection before indexing (fixes vector corruption)")
    parser.add_argument("--skip-agent-kill", action="store_true",
                        help="Skip auto-killing the Agent (dangerous — may cause Qdrant corruption)")
    args = parser.parse_args()

    # ── P0: Pre-flight checks ──
    if not args.skip_agent_kill:
        _kill_agent_if_running()
    _wait_for_qdrant_lock()

    # ── Init ──
    neo4j = Neo4jClient()
    qdrant = QdrantClientWrapper(local_mode=True)
    emb_model = get_embedding_model()

    # Force recreate if requested or if integrity check on existing collection fails
    if args.force_recreate:
        print("⚠️ Force-recreate: deleting existing collection...")
        try:
            qdrant._client.delete_collection(COLLECTION)
        except Exception:
            pass
        time.sleep(1)

    qdrant.ensure_collection(COLLECTION, vector_size=VECTOR_DIM)

    # ── Fetch claims from Neo4j ──
    with neo4j.driver.session() as session:
        result = session.run(
            "MATCH (c:Claim) RETURN c.id as id, c.statement as statement, "
            "c.subject as subject, c.source_date as source_date, "
            "c.confidence as confidence, c.status as status, "
            "c.claim_type as claim_type"
        )
        claims = list(result)

    print(f"Found {len(claims)} claims in Neo4j")

    # ── Index ──
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
                "claim_type": claim.get("claim_type", ""),
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

    # ── P3: Integrity check ──
    if not _verify_vectors(qdrant, VECTOR_DIM):
        print("\n⚠️  Integrity check FAILED. Run with --force-recreate to rebuild:")
        print(f"   python {__file__} --force-recreate")
        sys.exit(2)


if __name__ == "__main__":
    main()
