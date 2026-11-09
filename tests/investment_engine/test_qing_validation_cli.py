import json
import sqlite3
from pathlib import Path

import pytest

import scripts.qing_agent_validation as cli


DAY = "2026-07-15"


def _write_record(root):
    record = {
        "record_id": "cli-record",
        "date": DAY,
        "track": "pre_market",
        "generated_at": f"{DAY}T08:30:00+08:00",
        "data_as_of": f"{DAY}T08:00:00+08:00",
        "status": "pending_maturity",
        "final_judgment": {
            "market_stage": "震荡",
            "direction": "up",
            "horizon": "T+5",
            "trigger_conditions": ["confirmed"],
            "invalidation_conditions": ["invalidated"],
        },
        "raw_output": "CLI-RAW-SECRET",
        "expert_views": [{"school": "gator"}],
        "data_version": "data-v1",
        "rules_version": "rules-v1",
        "prompt_version": "prompt-v1",
        "review": {"passed": True, "notes": []},
        "settlement": None,
        "attribution": None,
        "input_snapshot": {"positions": ["CLI-POSITION-SECRET"]},
    }
    path = Path(root) / DAY / "pre_market" / "cli-record.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path


def _write_calendar(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE stocks_kline (trade_date TEXT)")
        conn.execute("INSERT INTO stocks_kline VALUES (?)", (DAY,))


def test_report_main_really_collects_and_writes_reports_without_settling(tmp_path, capsys):
    root = tmp_path / "records"
    out_dir = tmp_path / "out"
    db_path = tmp_path / "calendar.db"
    frozen_path = _write_record(root)
    before = frozen_path.read_bytes()
    _write_calendar(db_path)

    result = cli.main([
        "report", "--date", DAY, "--root", str(root), "--db", str(db_path),
        "--out-dir", str(out_dir),
    ])

    daily = out_dir / f"qing-agent-daily-{DAY}.md"
    reliability = out_dir / f"qing-agent-reliability-{DAY}.md"
    assert result == 0
    assert daily.is_file() and reliability.is_file()
    assert frozen_path.read_bytes() == before
    output = capsys.readouterr().out
    assert str(daily) in output and str(reliability) in output
    assert "CLI-RAW-SECRET" not in daily.read_text(encoding="utf-8")
    assert "CLI-POSITION-SECRET" not in daily.read_text(encoding="utf-8")


def test_settle_main_delegates_with_injected_paths_and_prints_stats(tmp_path, monkeypatch, capsys):
    calls = []

    def fake_settle(day, *, root, config_dir, db_path):
        calls.append((day, root, config_dir, db_path))
        return {"records": 2, "updated": 1, "items": 4}

    monkeypatch.setattr(cli, "settle_records", fake_settle)
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    config_dir = tmp_path / "config"

    result = cli.main([
        "settle", "--date", DAY, "--root", str(root), "--db", str(db_path),
        "--config-dir", str(config_dir), "--out-dir", str(tmp_path / "unused"),
    ])

    assert result == 0
    assert calls == [(DAY, root, config_dir, db_path)]
    assert "'records': 2" in capsys.readouterr().out


def test_run_main_orchestrates_settle_then_report(tmp_path, monkeypatch, capsys):
    calls = []

    def fake_settle(day, *, root, config_dir, db_path):
        calls.append(("settle", day, root, config_dir, db_path))
        return {"records": 1, "updated": 1}

    def fake_write(day, *, root, db_path, out_dir):
        calls.append(("report", day, root, db_path, out_dir))
        return {
            "daily": out_dir / f"qing-agent-daily-{day}.md",
            "reliability": out_dir / f"qing-agent-reliability-{day}.md",
        }

    monkeypatch.setattr(cli, "settle_records", fake_settle)
    monkeypatch.setattr(cli, "write_reports", fake_write)
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    config_dir = tmp_path / "config"
    out_dir = tmp_path / "out"

    result = cli.main([
        "run", "--date", DAY, "--root", str(root), "--db", str(db_path),
        "--config-dir", str(config_dir), "--out-dir", str(out_dir),
    ])

    assert result == 0
    assert calls == [
        ("settle", DAY, root, config_dir, db_path),
        ("report", DAY, root, db_path, out_dir),
    ]
    output = capsys.readouterr().out
    assert str(out_dir / f"qing-agent-daily-{DAY}.md") in output
    assert str(out_dir / f"qing-agent-reliability-{DAY}.md") in output


def test_run_main_unmocked_success_with_empty_root(tmp_path, capsys):
    root = tmp_path / "empty-records"
    out_dir = tmp_path / "out"
    db_path = tmp_path / "calendar.db"
    day = "2026-11-04"

    result = cli.main([
        "run", "--date", day, "--root", str(root), "--db", str(db_path),
        "--config-dir", str(tmp_path / "config"), "--out-dir", str(out_dir),
    ])

    assert result == 0
    assert (out_dir / f"qing-agent-daily-{day}.md").is_file()
    assert (out_dir / f"qing-agent-reliability-{day}.md").is_file()
    output = capsys.readouterr().out
    assert "[settle]" in output
    assert str(out_dir / f"qing-agent-daily-{day}.md") in output


@pytest.mark.parametrize("bad_day", ["not-a-date", "20261104"])
def test_run_main_invalid_date_has_no_settlement_or_report_side_effects(tmp_path, bad_day):
    root = tmp_path / "records"
    out_dir = tmp_path / "out"
    db_path = tmp_path / "calendar.db"
    frozen_path = _write_record(root)
    before = frozen_path.read_bytes()
    _write_calendar(db_path)

    with pytest.raises(ValueError):
        cli.main([
            "run", "--date", bad_day, "--root", str(root), "--db", str(db_path),
            "--config-dir", str(tmp_path / "config"), "--out-dir", str(out_dir),
        ])

    assert frozen_path.read_bytes() == before
    assert not out_dir.exists()
