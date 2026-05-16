from __future__ import annotations

from pathlib import Path


def build_markdown_index(root: Path, title: str) -> str:
    lines = [f"# {title}", "", "> 自动生成索引。", ""]
    files = sorted(path for path in root.rglob("*.md") if path.name != "index.md")
    for path in files:
        rel = path.relative_to(root).as_posix()
        lines.append(f"- [{rel}]({rel})")
    lines.append("")
    return "\n".join(lines)


def write_markdown_index(root: Path, title: str, index_name: str = "index.md") -> Path:
    index_path = root / index_name
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(build_markdown_index(root, title), encoding="utf-8")
    return index_path
