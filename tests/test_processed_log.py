from pathlib import Path

from qing_investment.processed_log import append_processed_source, load_processed_sources


def test_load_processed_sources_ignores_comments_and_blank_lines(tmp_path):
    log = tmp_path / "processed-log.md"
    log.write_text("# processed\n\n- sources/raw/财经/a.md\n- sources/raw/宏观/b.md\n", encoding="utf-8")
    assert load_processed_sources(log) == {"sources/raw/财经/a.md", "sources/raw/宏观/b.md"}


def test_append_processed_source_adds_bullet_once(tmp_path):
    log = tmp_path / "processed-log.md"
    log.write_text("# processed\n", encoding="utf-8")
    append_processed_source(log, Path("sources/raw/财经/a.md"))
    append_processed_source(log, Path("sources/raw/财经/a.md"))
    text = log.read_text(encoding="utf-8")
    assert text.count("- sources/raw/财经/a.md") == 1
