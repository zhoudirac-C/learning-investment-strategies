from qing_investment.index_builder import build_markdown_index


def test_build_markdown_index_lists_markdown_files(tmp_path):
    root = tmp_path / "knowledge" / "wiki"
    (root / "每日复盘").mkdir(parents=True)
    (root / "每日复盘" / "2026-05-16.md").write_text("# 复盘", encoding="utf-8")
    (root / "index.md").write_text("# old", encoding="utf-8")

    index = build_markdown_index(root, title="Wiki Index")

    assert "# Wiki Index" in index
    assert "每日复盘/2026-05-16.md" in index
    assert "index.md" not in index
