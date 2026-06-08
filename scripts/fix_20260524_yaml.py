#!/usr/bin/env python3
"""Fix 20260524 YAML files: normalize indentation to 2-space."""
from pathlib import Path

CLAIMS_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "claims"

def fix_indentation(filepath: Path) -> bool:
    text = filepath.read_text(encoding="utf-8")
    lines = text.split("\n")
    new_lines = []
    
    stack = []  # track indentation context
    in_links = False
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append("")
            continue
        
        # Determine logical nesting
        if stripped.startswith("id:"):
            new_lines.append(stripped)
            in_links = False
        elif stripped.startswith("links:"):
            new_lines.append("  " + stripped)
            in_links = True
        elif stripped.startswith("wiki_pages:") or stripped.startswith("methodology_pages:") or stripped.startswith("cases:"):
            indent = "    " if in_links else "  "
            new_lines.append(indent + stripped)
        elif stripped.startswith("- "):
            # List items — determine nesting level
            prev = new_lines[-1].strip() if new_lines else ""
            if prev.startswith("wiki_pages:") or prev.startswith("methodology_pages:") or prev.startswith("tags:"):
                indent = "      " if in_links else "    "
                new_lines.append(indent + stripped)
            else:
                new_lines.append("  " + stripped)
        elif stripped.startswith("intensity:") or stripped.startswith("tags:") or stripped.startswith("last_discovered:"):
            # Top-level keys (after closing links)
            new_lines.append(stripped)
            in_links = False
            if stripped.startswith("tags:"):
                pass  # list items follow
        elif ":" in stripped:
            # Generic key: value
            indent = "  " if (in_links and stripped not in ("intensity:", "tags:")) else ""
            new_lines.append(indent + stripped)
        else:
            new_lines.append("  " + stripped)
    
    result = "\n".join(new_lines) + "\n"
    if result != text:
        filepath.write_text(result, encoding="utf-8")
        return True
    return False


def main():
    fixed = 0
    for f in sorted(CLAIMS_DIR.glob("claim-20260524-*.yaml")):
        if fix_indentation(f):
            fixed += 1
            print(f"  Fixed: {f.name}")
    print(f"Done: {fixed} files")


if __name__ == "__main__":
    main()
