from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

RAW_DIR_NAMES = {"raw", "原始数据", "原文", "原数据"}
EXCLUDED_FILE_NAMES = {".DS_Store"}
EXCLUDED_DIR_NAMES = {".git", ".obsidian", "__pycache__", "Wiki", "wiki", "scripts", "log"}


def discover_raw_source_dirs(legacy_root: Path) -> list[Path]:
    legacy_root = legacy_root.resolve()
    if not legacy_root.exists():
        return []
    raw_dirs: list[Path] = []
    for path in sorted(item for item in legacy_root.rglob("*") if item.is_dir()):
        if _is_excluded_path(path, legacy_root):
            continue
        if _is_raw_dir_name(path.name):
            raw_dirs.append(path)
    return raw_dirs


def migrate_legacy_up_raw(legacy_root: Path, target_root: Path) -> dict[str, Any]:
    legacy_root = legacy_root.resolve()
    target_root = target_root.resolve()
    migration_dir = target_root / "migration"
    raw_dirs = discover_raw_source_dirs(legacy_root)

    raw_files: list[dict[str, str]] = []
    raw_directory_records: list[dict[str, str]] = []
    for raw_dir in raw_dirs:
        module = _module_name_for(raw_dir, legacy_root)
        raw_directory_records.append({"source": raw_dir.relative_to(legacy_root).as_posix(), "module": module})
        raw_files.extend(_copy_tree(raw_dir, target_root / "sources" / "raw" / module, module))

    manifest = {
        "legacy_root": str(legacy_root),
        "scope": "up-raw-only",
        "raw_directories": raw_directory_records,
        "raw_count": len(raw_files),
        "raw_files": raw_files,
        "excluded": [
            "*/Wiki/**",
            "*/scripts/**",
            "SKILL.md",
            "README.md",
            "*/schema.md",
            "*/trade_template.md",
            "log/**",
        ],
    }
    migration_dir.mkdir(parents=True, exist_ok=True)
    (migration_dir / "legacy-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (migration_dir / "legacy-source-map.md").write_text(_source_map_markdown(manifest), encoding="utf-8")
    return manifest


def _is_raw_dir_name(name: str) -> bool:
    return name.lower() == "raw" or name in RAW_DIR_NAMES


def _is_excluded_path(path: Path, legacy_root: Path) -> bool:
    relative_parts = path.relative_to(legacy_root).parts
    return any(part in EXCLUDED_DIR_NAMES for part in relative_parts)


def _module_name_for(raw_dir: Path, legacy_root: Path) -> str:
    parent = raw_dir.parent.relative_to(legacy_root)
    if parent.parts == ():
        return "_root"
    return parent.as_posix()


def _copy_tree(source_root: Path, target_root: Path, module: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        if source.name in EXCLUDED_FILE_NAMES:
            continue
        relative = source.relative_to(source_root)
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        records.append(_file_record(source, target, module))
    return records


def _file_record(source: Path, target: Path, module: str) -> dict[str, str]:
    return {
        "module": module,
        "source": str(source),
        "target": str(target),
        "sha256": _sha256(target),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_map_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Legacy UP Raw Source Map",
        "",
        f"- legacy_root: `{manifest['legacy_root']}`",
        "- scope: up-raw-only",
        f"- raw_count: {manifest['raw_count']}",
        "",
        "## 迁移规则",
        "",
        "| 来源 | 目标 |",
        "| --- | --- |",
    ]
    for record in manifest["raw_directories"]:
        lines.append(f"| `{record['source']}/**` | `sources/raw/{record['module']}/**` |")
    lines.extend(
        [
            "",
            "## 明确不迁移",
            "",
            "- `*/Wiki/**`",
            "- `*/scripts/**`",
            "- `SKILL.md`",
            "- `README.md`",
            "- `*/schema.md`",
            "- `*/trade_template.md`",
            "- `log/**`",
            "",
        ]
    )
    return "\n".join(lines)
