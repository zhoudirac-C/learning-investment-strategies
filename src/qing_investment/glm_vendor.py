from __future__ import annotations

import shutil
from pathlib import Path


def copy_glm_skill(source_root: Path, third_party_root: Path, vendor_root: Path) -> None:
    source_skill = source_root / "skills" / "glmv-stock-analyst"
    if not source_skill.exists():
        raise FileNotFoundError(f"Missing upstream skill directory: {source_skill}")

    third_party_skill = third_party_root / "skills" / "glmv-stock-analyst"
    if third_party_skill.exists():
        shutil.rmtree(third_party_skill)
    third_party_skill.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_skill, third_party_skill)

    license_source = source_root / "LICENSE"
    third_party_root.mkdir(parents=True, exist_ok=True)
    if license_source.exists():
        shutil.copy2(license_source, third_party_root / "LICENSE")

    if vendor_root.exists():
        shutil.rmtree(vendor_root)
    vendor_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(third_party_skill, vendor_root)
    patches = vendor_root / "PATCHES.md"
    patches.write_text(
        "# 本地 Patch 记录\n\n当前为 upstream 初始 vendor copy，尚未应用本地 patch。\n",
        encoding="utf-8",
    )


def write_vendor_metadata(third_party_root: Path, upstream_url: str, commit: str, synced_date: str) -> None:
    third_party_root.mkdir(parents=True, exist_ok=True)
    (third_party_root / "VENDOR.md").write_text(
        "# GLM-skills Vendor Metadata\n\n"
        f"- Upstream: {upstream_url}\n"
        "- Component: skills/glmv-stock-analyst\n"
        f"- Commit: {commit}\n"
        f"- Synced Date: {synced_date}\n"
        "- License: Apache-2.0\n",
        encoding="utf-8",
    )
