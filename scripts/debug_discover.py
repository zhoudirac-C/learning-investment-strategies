#!/usr/bin/env python3
"""Debug: trace discover pipeline for a single claim."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper
from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.tools.llm_client import get_embedding_model, get_llm_client

# Pick a claim that Neo4j says has relations
cid = "claim-20260607-001-c"  # 标普500 — Neo4j had this in a SUPERSEDES edge

# Load from the actual YAML
claims_dir = Path(__file__).resolve().parent.parent / "knowledge" / "claims"
claim = None
for yf in sorted(claims_dir.glob("*.yaml")):
    try:
        data = yaml.safe_load(yf.read_text(encoding="utf-8"))
    except Exception:
        continue
    claim_list = data if isinstance(data, list) else data.get("claims", [data] if isinstance(data, dict) else [data])
    if not isinstance(claim_list, list):
        claim_list = [claim_list]
    for c in claim_list:
        if isinstance(c, dict) and c.get("id") == cid:
            claim = c
            break
    if claim:
        break

if not claim:
    print(f"Claim {cid} not found!")
    sys.exit(1)

print(f"Claim: {cid} — {claim.get('statement', '')[:100]}")

# Step 1: Qdrant search
qdrant = QdrantClientWrapper()
emb = get_embedding_model()
text = f"{claim.get('subject', '')} | {claim.get('statement', '')}"
vec = emb.encode(text).tolist()
if isinstance(vec[0], list):
    vec = vec[0]

results = qdrant.search(vec, collection="qing_claims", limit=4)
print(f"\nQdrant search: {len(results)} results")
for r in results[:4]:
    pid = r.get("payload", {}).get("claim_id", "?")
    score = r.get("score", 0)
    tag = "(SELF)" if pid == cid else ""
    print(f"  {pid} score={score:.4f} {tag}")

# Step 2: fetch similar from Neo4j
neo4j = Neo4jClient()
for r in results[:4]:
    pid = r.get("payload", {}).get("claim_id", "?")
    if pid == cid or pid == "?":
        continue
    full = neo4j.get_claim_evolution(pid)
    if full:
        fdata = full[0] if isinstance(full, list) else full
        node = fdata.get("c", {}) if isinstance(fdata, dict) else (fdata[0].get("c", {}) if isinstance(fdata, list) and fdata else {})
        print(f"\nNeo4j for {pid}:")
        print(f"  node type: {type(node)}")
        if node:
            print(f"  subject: {node.get('subject', '?')[:80]}")
            print(f"  statement: {node.get('statement', '?')[:100]}")
    else:
        print(f"\nNeo4j for {pid}: None!")

neo4j.close()
