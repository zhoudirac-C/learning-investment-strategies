from pathlib import Path

from scripts.find_unprocessed import find_unprocessed


def test_find_unprocessed_excludes_processed(tmp_path):
    raw = tmp_path / "sources" / "raw" / "财经"
    raw.mkdir(parents=True)
    (raw / "2026-05-16-早盘-a.md").write_text("a", encoding="utf-8")
    (raw / "2026-05-16-午盘-b.md").write_text("b", encoding="utf-8")
    log = tmp_path / "sources" / "processed-log.md"
    log.write_text("# 已处理\n\n- sources/raw/财经/2026-05-16-早盘-a.md\n", encoding="utf-8")

    result = find_unprocessed(tmp_path)

    assert result == [Path("sources/raw/财经/2026-05-16-午盘-b.md")]
