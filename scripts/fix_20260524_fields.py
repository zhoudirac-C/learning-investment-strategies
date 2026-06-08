#!/usr/bin/env python3
"""Fix 20260524 files: add topic, tags, last_discovered, Neo4j relations."""
import re
from pathlib import Path
from neo4j import GraphDatabase

CLAIMS_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "claims"
FILES = [f"claim-20260524-{i:03d}" for i in range(1, 14)] + ["claim-20260524-019"]

# Map from 6facc98 commit for topic/tags
TOPICS = {}
TAGS = {}

def load_from_broken():
    """Extract topic and tags from the broken version in the current working tree (before revert)."""
    import subprocess
    for fname in FILES:
        # Show the file from 6facc98
        result = subprocess.run(
            ["git", "show", f"6facc98:knowledge/claims/{fname}.yaml"],
            capture_output=True, text=True, cwd=CLAIMS_DIR.parent.parent
        )
        if result.returncode == 0:
            text = result.stdout
            m = re.search(r'^topic:\s*(.+)$', text, re.MULTILINE)
            if m:
                TOPICS[fname] = m.group(1)
            # Extract tags block
            in_tags = False
            tags = []
            for line in text.split('\n'):
                if line.strip() == 'tags:':
                    in_tags = True
                elif in_tags and line.strip().startswith('- '):
                    tags.append(line.strip()[2:])
                elif in_tags and ':' in line and not line.strip().startswith('- '):
                    in_tags = False
            if tags:
                TAGS[fname] = tags

def fix_file(filepath: Path, neo4j_rels: dict, topic: str | None, tags: list | None) -> bool:
    text = filepath.read_text(encoding="utf-8")
    lines = text.split("\n")
    new_lines = []
    modified = False
    
    cid = Path(filepath).stem  # claim-20260524-001
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        new_lines.append(line)
        
        # After subject line, add topic if missing and we have it
        if stripped.startswith("subject:") and topic and "topic:" not in text:
            new_lines.append(f"topic: {topic}")
            modified = True
    
    # After status line, populate supersedes/contradicts from Neo4j
    result = "\n".join(new_lines)
    
    if cid in neo4j_rels:
        supers = [t for t, r in neo4j_rels[cid].items() if r == "SUPERSEDES"]
        contras = [t for t, r in neo4j_rels[cid].items() if r == "CONTRADICTS"]
        
        for key, vals in [("supersedes", supers), ("contradicts", contras)]:
            if vals and f"{key}: []" in result:
                ids = ", ".join(f'"{v}"' for v in vals)
                result = result.replace(f"{key}: []", f"{key}: [{ids}]")
                modified = True
    
    # Add tags after intensity if we have them
    if tags and "tags:" not in result:
        tag_lines = "tags:\n" + "\n".join(f"  - {t}" for t in tags)
        result = result.replace("intensity:", f"{tag_lines}\nintensity:")
        modified = True
    
    # Add last_discovered
    if "last_discovered:" not in result:
        result = result.rstrip() + "\n  last_discovered: 2026-06-08\n"
        modified = True
    
    if modified:
        filepath.write_text(result, encoding="utf-8")
    return modified


def main():
    load_from_broken()
    print(f"Loaded {len(TOPICS)} topics, {len(TAGS)} tag sets")
    
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "qingneo4j"))
    neo4j_rels = {}
    with driver.session() as s:
        for fname in FILES:
            result = s.run("""
                MATCH (a:Claim {id: $cid})-[r:SUPERSEDES|CONTRADICTS]->(b:Claim)
                RETURN type(r) as rel, b.id as tgt
            """, cid=fname).data()
            if result:
                neo4j_rels[fname] = {r["tgt"]: r["rel"] for r in result}
    driver.close()
    
    fixed = 0
    for fname in FILES:
        path = CLAIMS_DIR / f"{fname}.yaml"
        if fix_file(path, neo4j_rels, TOPICS.get(fname), TAGS.get(fname)):
            fixed += 1
            print(f"  Fixed: {fname}.yaml")
    print(f"\nDone: {fixed} files")


if __name__ == "__main__":
    main()
