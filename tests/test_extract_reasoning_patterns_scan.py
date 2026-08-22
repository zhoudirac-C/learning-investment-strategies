"""extract_reasoning_patterns.scan_candidates 的多目录与 --since 过滤测试。"""

from scripts.extract_reasoning_patterns import scan_candidates


def _mkfiles(d, specs):
    for name, size in specs:
        p = d / name
        p.write_text("x" * size, encoding="utf-8")


def test_scan_covers_multiple_dirs_and_since_filter(tmp_path):
    dir_a = tmp_path / "财经"
    dir_b = tmp_path / "bilibili"
    dir_a.mkdir()
    dir_b.mkdir()
    _mkfiles(dir_a, [
        ("2026-08-10-复盘-旧目录新文件.md", 3000),
        ("2026-07-01-复盘-旧文件.md", 3000),
        ("周复盘：无日期前缀.md", 3000),
        ("2026-08-11-视频-太小.md", 400),
    ])
    _mkfiles(dir_b, [
        ("2026-08-09-2018-视频-b站周复盘.md", 3000),
        ("2026-08-21-0959-图片-短动态.md", 2000),
    ])

    state = {"processed_files": []}
    files = scan_candidates(state, incremental=True, since="2026-08-08", raw_dirs=[dir_a, dir_b])
    names = sorted(f.name for f in files)

    # 两个目录的窗口内文件都入选
    assert "2026-08-10-复盘-旧目录新文件.md" in names
    assert "2026-08-09-2018-视频-b站周复盘.md" in names
    assert "2026-08-21-0959-图片-短动态.md" in names
    # 窗口外、无日期前缀、过小文件都被排除
    assert "2026-07-01-复盘-旧文件.md" not in names
    assert "周复盘：无日期前缀.md" not in names
    assert "2026-08-11-视频-太小.md" not in names


def test_scan_incremental_skips_processed_basename(tmp_path):
    dir_a = tmp_path / "财经"
    dir_a.mkdir()
    _mkfiles(dir_a, [("2026-08-10-复盘-已处理.md", 3000), ("2026-08-11-复盘-未处理.md", 3000)])

    state = {"processed_files": ["2026-08-10-复盘-已处理.md"]}
    files = scan_candidates(state, incremental=True, since="2026-08-08", raw_dirs=[dir_a])
    assert [f.name for f in files] == ["2026-08-11-复盘-未处理.md"]


def test_scan_without_since_keeps_undated_files(tmp_path):
    dir_a = tmp_path / "财经"
    dir_a.mkdir()
    _mkfiles(dir_a, [("周复盘：26-06-07：无日期前缀.md", 3000)])

    files = scan_candidates({}, incremental=False, since=None, raw_dirs=[dir_a])
    assert [f.name for f in files] == ["周复盘：26-06-07：无日期前缀.md"]
