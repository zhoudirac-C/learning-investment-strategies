#!/usr/bin/env python3
"""
Migrate Qdrant data from local SQLite mode to remote server mode.

Usage:
    cd ~/learning-investment-strategies
    PYTHONPATH=src .venv/bin/python3 scripts/migrate_qdrant_local_to_remote.py
"""

import sys
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
import numpy as np

LOCAL_PATH = ".qdrant_data"
REMOTE_HOST = "localhost"
REMOTE_PORT = 6333


def migrate_collection(local: QdrantClient, remote: QdrantClient, coll_name: str):
    """Migrate all points from local to remote collection."""
    print(f"\n=== Migrating {coll_name} ===")

    # Get local count
    local_info = local.get_collection(coll_name)
    print(f"Local: {local_info.points_count} points")

    # Scroll all points from local
    all_points = []
    offset = None
    batch_num = 0
    while True:
        batch, offset = local.scroll(
            collection_name=coll_name,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not batch:
            break

        for p in batch:
            # Convert to PointStruct (remote accepts UUID or int)
            pid = p.id if isinstance(p.id, (int, str)) else str(p.id)
            vec = p.vector
            if vec is None:
                raise ValueError(f"Point {pid} has no vector")
            if isinstance(vec, dict):
                raise ValueError(f"Point {pid} has multi-vector (dict), not supported")
            # Handle nested list from local SQLite mode: [[v1, v2, ...]] → [v1, v2, ...]
            if isinstance(vec, list) and len(vec) > 0 and isinstance(vec[0], list):
                vec = vec[0]
            all_points.append(PointStruct(
                id=pid,
                vector=vec,
                payload=p.payload or {},
            ))

        batch_num += 1
        if batch_num % 10 == 0:
            print(f"  Scrolled {len(all_points)} points...")

        if offset is None:
            break

    print(f"  Total scrolled: {len(all_points)} points")

    if not all_points:
        print(f"  No points to migrate for {coll_name}")
        return 0

    # Batch upsert to remote
    batch_size = 100
    for i in range(0, len(all_points), batch_size):
        batch_pts = all_points[i:i + batch_size]
        remote.upsert(collection_name=coll_name, points=batch_pts)
        if (i // batch_size + 1) % 10 == 0:
            print(f"  Upserted {min(i + batch_size, len(all_points))}/{len(all_points)}...")

    print(f"  Upsert complete: {len(all_points)} points")

    # Verify count
    remote_info = remote.get_collection(coll_name)
    print(f"Remote: {remote_info.points_count} points")

    if remote_info.points_count != len(all_points):
        print(f"  ERROR: Count mismatch! local={len(all_points)}, remote={remote_info.points_count}")
        return 1

    print(f"  ✓ Count matches")
    return 0


def spot_check(local: QdrantClient, remote: QdrantClient, coll_name: str):
    """Spot-check random points for vector + payload equality."""
    print(f"\n=== Spot-check {coll_name} ===")

    local_pts, _ = local.scroll(coll_name, limit=10, with_vectors=True, with_payload=True)
    mismatches = 0

    for lp in local_pts:
        vec = lp.vector
        if vec is None:
            print(f"  id={lp.id}: SKIP (no vector)")
            continue
        # Handle nested list from local SQLite mode
        if isinstance(vec, list) and len(vec) > 0 and isinstance(vec[0], list):
            vec = vec[0]

        # Retrieve remote point by ID directly
        try:
            rp_list = remote.retrieve(
                collection_name=coll_name,
                ids=[lp.id],
                with_vectors=True,
                with_payload=True,
            )
            if not rp_list:
                print(f"  id={lp.id}: NOT FOUND in remote")
                mismatches += 1
                continue
            rp = rp_list[0]
        except Exception as e:
            print(f"  id={lp.id}: RETRIEVE ERROR: {e}")
            mismatches += 1
            continue

        # Compare vectors
        rvec = rp.vector
        if isinstance(rvec, list) and len(rvec) > 0 and isinstance(rvec[0], list):
            rvec = rvec[0]

        vec_match = np.allclose(np.array(vec), np.array(rvec), atol=1e-6)
        payload_match = lp.payload == rp.payload

        if not vec_match:
            print(f"  id={lp.id}: VECTOR MISMATCH")
            mismatches += 1
        if not payload_match:
            print(f"  id={lp.id}: PAYLOAD MISMATCH")
            mismatches += 1

    if mismatches == 0:
        print(f"  ✓ All {len(local_pts)} spot-checks passed")
    else:
        print(f"  ✗ {mismatches} mismatches found")
    return mismatches


def main():
    print("Qdrant Local → Remote Migration")
    print("=" * 50)

    local = QdrantClient(path=LOCAL_PATH)
    remote = QdrantClient(host=REMOTE_HOST, port=REMOTE_PORT)

    # Verify remote is reachable
    try:
        remote.get_collections()
        print(f"Remote Qdrant at {REMOTE_HOST}:{REMOTE_PORT} is reachable")
    except Exception as e:
        print(f"ERROR: Cannot connect to remote Qdrant: {e}")
        sys.exit(1)

    errors = 0
    for coll_name in ["qing_claims", "qing_knowledge"]:
        errors += migrate_collection(local, remote, coll_name)
        errors += spot_check(local, remote, coll_name)

    print("\n" + "=" * 50)
    if errors == 0:
        print("Migration completed successfully ✓")
    else:
        print(f"Migration completed with {errors} errors ✗")
        sys.exit(1)


if __name__ == "__main__":
    main()
