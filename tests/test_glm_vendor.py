from qing_investment.glm_vendor import copy_glm_skill, write_vendor_metadata


def test_copy_glm_skill_copies_required_files(tmp_path):
    source_root = tmp_path / "source"
    skill = source_root / "skills" / "glmv-stock-analyst"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: glmv-stock-analyst\ndescription: test\n---\n", encoding="utf-8")
    (source_root / "LICENSE").write_text("Apache License 2.0", encoding="utf-8")

    third_party = tmp_path / "third_party" / "GLM-skills"
    vendor = tmp_path / "skills" / "qing-stock-analysis" / "vendor" / "glmv-stock-analyst"

    copy_glm_skill(source_root=source_root, third_party_root=third_party, vendor_root=vendor)

    assert (third_party / "skills" / "glmv-stock-analyst" / "SKILL.md").exists()
    assert (third_party / "LICENSE").read_text(encoding="utf-8") == "Apache License 2.0"
    assert (vendor / "SKILL.md").exists()
    assert (vendor / "PATCHES.md").exists()


def test_write_vendor_metadata_records_commit(tmp_path):
    write_vendor_metadata(
        tmp_path,
        upstream_url="https://github.com/zai-org/GLM-skills",
        commit="abc123",
        synced_date="2026-05-16",
    )
    text = (tmp_path / "VENDOR.md").read_text(encoding="utf-8")
    assert "abc123" in text
    assert "Apache-2.0" in text
