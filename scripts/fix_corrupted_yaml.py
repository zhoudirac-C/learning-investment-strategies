#!/usr/bin/env python3
"""Fix corrupted YAML: remove stray claim IDs + populate supersedes/contradicts from Neo4j."""
import re
from pathlib import Path

from neo4j import GraphDatabase

CLAIMS_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "claims"

def fix_file(filepath: Path, neo4j_rels: dict) -> bool:
    text = filepath.read_text(encoding="utf-8")
    lines = text.split("\n")
    new_lines = []
    i = 0
    modified = False
    
    while i < len(lines):
        line = lines[i]
        trimmed = line.strip()
        
        # Skip stray - claim-xxx lines (not valid YAML at this indentation)
        if re.match(r'^\s*-\s*claim-\S+', line) and i > 0:
            prev_trimmed = new_lines[-1].strip() if new_lines else ""
            # If previous line is supersedes: [...] or contradicts: [..], this is a stray
            if prev_trimmed.startswith("supersedes:") or prev_trimmed.startswith("contradicts:"):
                modified = True
                i += 1
                continue
        
        # Populate supersedes: [] from Neo4j
        if trimmed == "supersedes: []":
            indent = line[:len(line) - len(line.lstrip())]
            cid = _find_id(new_lines)
            if cid and cid in neo4j_rels:
                supers = [t for t, r in neo4j_rels[cid].items() if r == "SUPERSEDES"]
                if supers:
                    ids = ", ".join(f'"{s}"' for s in supers)
                    new_lines.append(f"{indent}supersedes: [{ids}]")
                    modified = True
                    i += 1
                    continue
            new_lines.append(line)
            i += 1
            continue
        
        # Populate contradicts: [] from Neo4j
        if trimmed == "contradicts: []":
            indent = line[:len(line) - len(line.lstrip())]
            cid = _find_id(new_lines)
            if cid and cid in neo4j_rels:
                contras = [t for t, r in neo4j_rels[cid].items() if r == "CONTRADICTS"]
                if contras:
                    ids = ", ".join(f'"{c}"' for c in contras)
                    new_lines.append(f"{indent}contradicts: [{ids}]")
                    modified = True
                    i += 1
                    continue
            new_lines.append(line)
            i += 1
            continue
        
        new_lines.append(line)
        i += 1
    
    if modified:
        filepath.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return modified


def _find_id(lines: list[str]) -> str | None:
    for line in reversed(lines):
        m = re.search(r'id:\s*(claim-\S+)', line)
        if m:
            return m.group(1)
    return None


def main():
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "qingneo4j"))
    
    # Load all Neo4j relations
    neo4j_rels = {}
    with driver.session() as s:
        for rec in s.run("MATCH (a:Claim)-[r:SUPERSEDES|CONTRADICTS]->(b:Claim) RETURN a.id as src, type(r) as rel, b.id as tgt"):
            neo4j_rels.setdefault(rec["src"], {})[rec["tgt"]] = rec["rel"]
    driver.close()
    print(f"Neo4j: {len(neo4j_rels)} claims with relations")
    
    # Fix all YAMLs
    fixed = 0
    for yf in sorted(CLAIMS_DIR.glob("*.yaml")):
        if fix_file(yf, neo4j_rels):
            fixed += 1
            print(f"  Fixed: {yf.name}")
    print(f"\nDone. Fixed {fixed} files.")


if __name__ == "__main__":
    main()
