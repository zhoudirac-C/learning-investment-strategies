#!/usr/bin/env python3
"""
LLM-powered claim relationship discovery.

For each claim without existing relationships (supersedes/contradicts),
finds top-3 similar claims via Qdrant embedding search, then asks LLM
to judge the relation type.

Modes:
  --file PATH         Process a single claim file
  --claim-id ID       Process a single claim by ID
  --all-missing       Process all claims missing relationships
  --dry-run           Judge but don't write back to YAML files

Output: updates claim YAML files with supersedes/contradicts fields.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

# ──────────────────────────────────────────────────────────────────
# ⚠️ 此脚本已从 scripts/ 迁移至 src/qing_investment/agent/tools/
# 运行命令：
#   PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing
# 或：
#   cd /path/to/learning-investment-strategies && PYTHONPATH=src .venv/bin/python -m qing_investment.agent.tools.discover_claim_relations --all-missing
# ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent  # src/qing_investment/agent/tools/ → repo root
# Python auto-adds script directory to sys.path[0], which shadows pip packages (e.g. qdrant_client)
_script_dir = str(Path(__file__).resolve().parent)
if sys.path and sys.path[0] == _script_dir:
    sys.path.pop(0)
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import numpy as np
from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.tools.llm_client import get_embedding_model, get_llm_client
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper

COLLECTION = "qing_claims"

RELATION_PROMPT = """你是投资研究助手。请判断两条投资观点 claim 之间的关系。

Claim A（新）:
  主题: {subject_a}
  表述: {statement_a}
  解释: {interpretation_a}
  日期: {date_a}
  类型: {type_a}

Claim B（已有）:
  主题: {subject_b}
  表述: {statement_b}
  解释: {interpretation_b}
  日期: {date_b}
  类型: {type_b}

关系类型（选一个）：
- supersedes: A 取代了 B（A 是更新的判断，B 已过时，方向一致但 A 更新更精确）
- supplements: A 补充了 B（方向一致或扩大范围，A 增加了细节、标的或证据）
- contradicts: A 与 B 矛盾（方向相反，或关键判断冲突）
- none: 无直接关系（主题不同，或虽有交集但不构成呼应/冲突）

注意：
- 同一主题不同时间，新观点通常 supersedes 旧观点（如"磨底期买科技"→"磨底期回避科技"=supersedes）
- 同一方向增加标的清单 = supplements
- 市场周期判断方向相反 = contradicts（如"看多半导体" vs "规避半导体"）
- 仅因共享板块但观点不呼应 = none

以 JSON 格式回复（只输出 JSON）：
{{"relation": "supersedes|supplements|contradicts|none", "reason": "简短中文说明（<50字）"}}"""


def find_similar_claims(
    claim: dict, qdrant: QdrantClientWrapper, emb_model, top_k: int = 3
) -> list[dict]:
    """Find top-k similar claims via Qdrant embedding search."""
    text = f"{claim.get('subject', '')} | {claim.get('statement', '')}"
    vec = emb_model.encode(text).tolist()
    if isinstance(vec[0], list):
        vec = vec[0]  # handle batch wrapper

    results = qdrant.search(vec, collection=COLLECTION, limit=top_k + 1)
    similar = []
    cid = claim.get("id", "")
    for r in results:
        payload = r.get("payload", {}) or {}
        rid = payload.get("claim_id", "")
        if rid and rid != cid:  # exclude self
            similar.append({
                "id": rid,
                "subject": payload.get("subject", ""),
                "statement": payload.get("statement", ""),
                "source_date": payload.get("source_date", ""),
                "claim_type": payload.get("claim_type", ""),
                "score": r.get("score", 0),
            })
        if len(similar) >= top_k:
            break
    return similar


def fetch_full_claim(claim_id: str, neo4j: Neo4jClient) -> dict | None:
    """Fetch full claim details from Neo4j."""
    result = neo4j.get_claim_evolution(claim_id)
    if not result:
        return None
    first = result[0] if isinstance(result, list) else result
    if not isinstance(first, dict):
        return None
    # Result is flat dict: {"id": ..., "statement": ..., "subject": ...}
    if not first.get("statement"):
        return None
    return {
        "id": claim_id,
        "subject": first.get("subject", ""),
        "statement": first.get("statement", ""),
        "interpretation": first.get("interpretation", ""),
        "source_date": str(first.get("source_date", "")),
        "claim_type": first.get("claim_type", ""),
    }


def judge_relation(claim_a: dict, claim_b: dict, llm) -> dict:
    """Ask LLM to judge the relation between two claims."""
    prompt = RELATION_PROMPT.format(
        subject_a=claim_a.get("subject", ""),
        statement_a=claim_a.get("statement", ""),
        interpretation_a=claim_a.get("interpretation", "")[:300],
        date_a=claim_a.get("source_date", ""),
        type_a=claim_a.get("claim_type", ""),
        subject_b=claim_b.get("subject", ""),
        statement_b=claim_b.get("statement", ""),
        interpretation_b=claim_b.get("interpretation", "")[:300],
        date_b=claim_b.get("source_date", ""),
        type_b=claim_b.get("claim_type", ""),
    )
    try:
        resp = llm.invoke(prompt).content or ""
        # Extract JSON from response
        resp = resp.strip()
        if resp.startswith("```"):
            resp = resp.split("\n", 1)[1]
            if resp.endswith("```"):
                resp = resp[:-3]
        return json.loads(resp)
    except (json.JSONDecodeError, Exception) as e:
        return {"relation": "none", "reason": f"LLM parse error: {e}"}


def process_claim(
    claim: dict,
    qdrant: QdrantClientWrapper,
    neo4j: Neo4jClient,
    emb_model,
    llm,
    dry_run: bool = False,
) -> dict:
    """Process a single claim: find similar, judge relations, return results."""
    cid = claim.get("id", "")
    results = {"claim_id": cid, "supersedes": [], "contradicts": [], "pairs": []}

    similar = find_similar_claims(claim, qdrant, emb_model, top_k=3)
    if not similar:
        return results

    for sim in similar:
        # Fetch full details for the similar claim
        sim_full = fetch_full_claim(sim["id"], neo4j)
        if not sim_full:
            continue

        # Ask LLM
        judgment = judge_relation(claim, sim_full, llm)
        relation = judgment.get("relation", "none")
        pair_info = {
            "target_id": sim["id"],
            "relation": relation,
            "reason": judgment.get("reason", ""),
            "score": sim.get("score", 0),
        }
        results["pairs"].append(pair_info)

        if relation == "supersedes":
            if sim["id"] not in results["supersedes"]:
                results["supersedes"].append(sim["id"])
        elif relation == "contradicts":
            if sim["id"] not in results["contradicts"]:
                results["contradicts"].append(sim["id"])

    return results


def write_results_to_yaml(file_path: Path, claim_id: str, results: dict, dry_run: bool, force: bool = False):
    """Update YAML file with discovered relations and last_discovered timestamp."""
    if dry_run:
        print(f"  [DRY RUN] Would update {file_path.name} → {claim_id}")
        return

    text = file_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    new_lines = []
    updated = False
    today_str = datetime.now().strftime("%Y-%m-%d")

    i = 0
    while i < len(lines):
        line = lines[i]

        # Find the claim block by ID
        if f"id: {claim_id}" in line or f"id: \"{claim_id}\"" in line or f"id: '{claim_id}'" in line:
            new_lines.append(line)
            i += 1

            # Find and replace supersedes/contradicts in this block
            block_claims_id = claim_id
            has_last_discovered = False
            while i < len(lines):
                line = lines[i]
                # Stop at next claim
                if line.strip().startswith("- id:") or line.strip().startswith("id:"):
                    # Check if it's a different claim
                    if claim_id not in line:
                        break

                if line.strip().startswith("last_discovered:"):
                    has_last_discovered = True

                if line.strip().startswith("supersedes:"):
                    indent = line[:len(line) - len(line.lstrip())]
                    new_lines.append(f"{indent}supersedes: {json.dumps(results['supersedes'])}")
                    updated = True
                    i += 1
                    # Skip orphan list items from old YAML format (e.g. "    - claim-xxx")
                    while i < len(lines) and lines[i].strip().startswith("- claim-"):
                        i += 1
                    continue
                elif line.strip().startswith("contradicts:"):
                    indent = line[:len(line) - len(line.lstrip())]
                    new_lines.append(f"{indent}contradicts: {json.dumps(results['contradicts'])}")
                    updated = True
                    i += 1
                    # Skip orphan list items from old YAML format
                    while i < len(lines) and lines[i].strip().startswith("- claim-"):
                        i += 1
                    # Write last_discovered right after contradicts (avoid tags sequence conflict)
                    if results.get("supersedes") or results.get("contradicts") or force:
                        new_lines.append(f"{indent}last_discovered: {today_str}")
                        updated = True
                        has_last_discovered = True
                    continue
                elif line.strip().startswith("last_discovered:"):
                    # Already has a last_discovered line, skip it (will re-add below)
                    i += 1
                    continue

                new_lines.append(line)
                i += 1

            # Append last_discovered after the claim block (only if not already written above)
            if not has_last_discovered:
                indent = "  "
                for nl in reversed(new_lines):
                    trimmed = nl.strip()
                    if trimmed.startswith("supersedes:") or trimmed.startswith("contradicts:"):
                        indent_guess = nl[:len(nl) - len(nl.lstrip())]
                        if indent_guess:
                            indent = indent_guess
                        break
                if results.get("supersedes") or results.get("contradicts") or force:
                    new_lines.append(f"{indent}last_discovered: {today_str}")
                    updated = True
            continue

        new_lines.append(line)
        i += 1

    if updated:
        file_path.write_text("\n".join(new_lines), encoding="utf-8")


def _parse_claims(data) -> list[dict]:
    """Parse claims from YAML data, handling multiple formats."""
    if data is None:
        return []
    if isinstance(data, list):
        # data is already a list of claims
        return [c for c in data if isinstance(c, dict)]
    if isinstance(data, dict):
        if "claims" in data:
            claims = data["claims"]
            return claims if isinstance(claims, list) else [claims]
        return [data]
    return []


def main():
    parser = argparse.ArgumentParser(description="Discover claim relations via LLM")
    parser.add_argument("--file", type=str, help="Process a single claim YAML file")
    parser.add_argument("--claim-id", type=str, help="Process a single claim by ID")
    parser.add_argument("--all-missing", action="store_true", help="Process all claims missing relations")
    parser.add_argument("--dry-run", action="store_true", help="Judge but don't write back")
    parser.add_argument("--limit", type=int, default=0, help="Max claims to process (for testing)")
    args = parser.parse_args()

    # Init
    qdrant = QdrantClientWrapper(local_mode=True)
    neo4j = Neo4jClient()
    emb_model = get_embedding_model()
    llm = get_llm_client()

    # Collect claims to process
    to_process: list[tuple[Path, dict]] = []

    if args.file:
        path = Path(args.file)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for c in _parse_claims(data):
            if isinstance(c, dict) and c.get("id"):
                to_process.append((path, c))

    elif args.claim_id:
        # Search all YAML files for this claim
        claims_dir = PROJECT_ROOT / "knowledge" / "claims"
        found = False
        for yf in sorted(claims_dir.glob("*.yaml")):
            data = yaml.safe_load(yf.read_text(encoding="utf-8"))
            for c in _parse_claims(data):
                if isinstance(c, dict) and c.get("id") == args.claim_id:
                    to_process.append((yf, c))
                    found = True
                    break
            if found:
                break

    elif args.all_missing:
        claims_dir = PROJECT_ROOT / "knowledge" / "claims"
        for yf in sorted(claims_dir.glob("*.yaml")):
            data = yaml.safe_load(yf.read_text(encoding="utf-8"))
            for c in _parse_claims(data):
                if not isinstance(c, dict):
                    continue
                # Skip if already discovered (supersedes/contradicts or supplements/none)
                if c.get("last_discovered"):
                    continue
                if c.get("id"):
                    to_process.append((yf, c))

    else:
        print("Please specify --file, --claim-id, or --all-missing")
        sys.exit(1)

    if args.limit:
        to_process = to_process[:args.limit]

    print(f"Processing {len(to_process)} claims...")

    total_relations = 0
    for i, (path, claim) in enumerate(to_process):
        cid = claim.get("id", "?")
        print(f"[{i+1}/{len(to_process)}] {cid}: {claim.get('subject', '')[:50]}")

        results = process_claim(claim, qdrant, neo4j, emb_model, llm, dry_run=args.dry_run)

        for p in results["pairs"]:
            tag = {"supersedes": "↻", "supplements": "+", "contradicts": "✗", "none": "·"}.get(p["relation"], "?")
            print(f"  {tag} {p['relation']:12s} → {p['target_id']} (sim={p['score']:.3f}) {p['reason']}")
            if p["relation"] in ("supersedes", "contradicts"):
                total_relations += 1

        # Always write last_discovered timestamp (even if only supplements/none found)
        write_results_to_yaml(path, cid, results, args.dry_run, force=True)

    neo4j.close()
    print(f"\n✅ Done. Found {total_relations} supersedes/contradicts relations.")
    if args.dry_run:
        print("   (dry-run mode, no files modified)")


if __name__ == "__main__":
    main()
