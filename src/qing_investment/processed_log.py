from __future__ import annotations

from pathlib import Path


def load_processed_sources(path: Path) -> set[str]:
    if not path.exists():
        return set()
    processed: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            processed.add(stripped[2:].strip())
    return processed


def append_processed_source(path: Path, source_path: Path) -> None:
    source = source_path.as_posix()
    processed = load_processed_sources(path)
    if source in processed:
        return
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 已处理 Raw 文件\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"- {source}\n")
