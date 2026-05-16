from pathlib import Path

from qing_investment.legacy_migration import discover_raw_source_dirs, migrate_legacy_up_raw


def build_legacy_fixture(root: Path) -> Path:
    legacy = root / "赛博青哥wiki"
    (legacy / "财经" / "Raw").mkdir(parents=True)
    (legacy / "宏观" / "raw").mkdir(parents=True)
    (legacy / "访谈" / "原文").mkdir(parents=True)
    (legacy / "财经" / "Wiki" / "每日复盘").mkdir(parents=True)
    (legacy / "财经" / "scripts").mkdir(parents=True)
    (legacy / "财经" / "Raw" / "2026-05-16-早盘-a.md").write_text("raw a", encoding="utf-8")
    (legacy / "财经" / "Raw" / "2026-05-16-午盘-b.md").write_text("raw b", encoding="utf-8")
    (legacy / "宏观" / "raw" / "2026-05-16-宏观.md").write_text("macro raw", encoding="utf-8")
    (legacy / "访谈" / "原文" / "2026-05-16-访谈.txt").write_text("interview raw", encoding="utf-8")
    (legacy / "财经" / "Wiki" / "每日复盘" / "2026-05-16.md").write_text("wiki should not migrate", encoding="utf-8")
    (legacy / "SKILL.md").write_text("skill should not migrate", encoding="utf-8")
    (legacy / "财经" / "scripts" / "coarse_screen.py").write_text("print('should not migrate')", encoding="utf-8")
    return legacy


def test_discover_raw_source_dirs_finds_all_up_raw_dirs(tmp_path):
    legacy = build_legacy_fixture(tmp_path)

    dirs = {path.relative_to(legacy).as_posix() for path in discover_raw_source_dirs(legacy)}

    assert dirs == {"财经/Raw", "宏观/raw", "访谈/原文"}


def test_migrate_legacy_up_raw_copies_all_raw_modules_only(tmp_path):
    legacy = build_legacy_fixture(tmp_path)
    target = tmp_path / "target"

    manifest = migrate_legacy_up_raw(legacy_root=legacy, target_root=target)

    assert manifest["scope"] == "up-raw-only"
    assert manifest["raw_count"] == 4
    assert {entry["module"] for entry in manifest["raw_files"]} == {"财经", "宏观", "访谈"}
    assert (target / "sources" / "raw" / "财经" / "2026-05-16-早盘-a.md").exists()
    assert (target / "sources" / "raw" / "财经" / "2026-05-16-午盘-b.md").exists()
    assert (target / "sources" / "raw" / "宏观" / "2026-05-16-宏观.md").exists()
    assert (target / "sources" / "raw" / "访谈" / "2026-05-16-访谈.txt").exists()
    assert not (target / "knowledge" / "wiki" / "每日复盘" / "2026-05-16.md").exists()
    assert not (target / "knowledge" / "legacy" / "finance-wiki.SKILL.md").exists()
    assert not (target / "knowledge" / "legacy" / "scripts" / "coarse_screen.py").exists()
    assert (target / "migration" / "legacy-manifest.json").exists()
    assert (target / "migration" / "legacy-source-map.md").exists()
