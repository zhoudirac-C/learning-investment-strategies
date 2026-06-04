#!/usr/bin/env python3
"""
Initialize memory store for qing-agent.

Since the Mem0 server is not running, this script builds a local JSON-based
memory file that the agent's Mem0ClientWrapper can read as a fallback.

Sources:
- framework/ -> agent_preference (methodology, trading rules, output contracts)
- knowledge/claims/*.yaml -> recent active claims as facts
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MEMORY_FILE = REPO_ROOT / "infra" / "data" / "local_memories.json"
FRAMEWORK_DIR = REPO_ROOT / "framework"
CLAIMS_DIR = REPO_ROOT / "knowledge" / "claims"


def load_yaml_safe(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "claims" in data:
        claims = data["claims"]
        return claims if isinstance(claims, list) else [claims]
    if isinstance(data, dict):
        return [data]
    return []


def main():
    memories = []

    # 1. Framework files -> agent_preference
    framework_files = sorted(FRAMEWORK_DIR.glob("*.md"))
    print(f"Loading {len(framework_files)} framework files...")
    for fp in framework_files:
        content = fp.read_text(encoding="utf-8")
        # Truncate very long files to first 2000 chars for memory storage
        summary = content[:2000]
        memories.append({
            "id": f"framework-{fp.stem}",
            "type": "agent_preference",
            "content": summary,
            "source": str(fp.relative_to(REPO_ROOT)),
            "metadata": {"category": "framework", "title": fp.stem},
        })

    # 2. Recent active claims -> fact
    yaml_files = sorted(glob.glob(str(CLAIMS_DIR / "*.yaml")))
    active_claims = []
    for fp in yaml_files:
        claims = load_yaml_safe(Path(fp))
        for c in claims:
            if isinstance(c, dict) and c.get("status") == "active":
                active_claims.append(c)

    # Sort by source_date desc, take latest 50
    def _date_key(x):
        d = x.get("source_date", "")
        if hasattr(d, "isoformat"):
            return d.isoformat()
        return str(d)
    active_claims.sort(key=_date_key, reverse=True)
    recent_claims = active_claims[:50]
    print(f"Loading {len(recent_claims)} recent active claims...")

    for c in recent_claims:
        memories.append({
            "id": c.get("id", ""),
            "type": "fact",
            "content": f"[{c.get('claim_type', '')}] {c.get('subject', '')}: {c.get('statement', '')}",
            "source": c.get("source_path", ""),
            "metadata": {
                "confidence": c.get("confidence", "medium"),
                "timeframe": c.get("timeframe", ""),
                "status": c.get("status", ""),
            },
        })

    # 3. Write local memory file
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(memories, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Wrote {len(memories)} memories to {MEMORY_FILE}")


if __name__ == "__main__":
    main()
