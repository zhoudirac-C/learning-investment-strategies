"""graduation：窗口聚合与毕业判定。"""
import json
from datetime import date

from investment_engine.shadow.graduation import (
    aggregate, judge, load_records, window_records, weekly_breakdown,
)

TODAY = date(2026, 8, 9)  # 周日；所在 ISO 周周一 = 2026-08-03


def _rec(day, *, stage_hit=None, status="scored", dirs=None):
    rec = {"date": day, "status": status, "stage_hit": stage_hit}
    if dirs is not None:
        rec["due_scores"] = {"directions": dirs}
    return rec


def _write(tmp_path, records):
    pred_dir = tmp_path / "predictions"
    pred_dir.mkdir()
    for r in records:
        (pred_dir / f"{r['date']}.json").write_text(
            json.dumps(r, ensure_ascii=False), encoding="utf-8")
    return pred_dir


def test_load_records_skips_bad_and_missing_date(tmp_path):
    pred_dir = _write(tmp_path, [_rec("2026-08-05", stage_hit=True)])
    (pred_dir / "bad.json").write_text("{not json", encoding="utf-8")
    (pred_dir / "nodate.json").write_text("{}", encoding="utf-8")
    records, skipped = load_records(pred_dir)
    assert len(records) == 1 and skipped == 2


def test_load_records_missing_dir(tmp_path):
    records, skipped = load_records(tmp_path / "nonexistent")
    assert records == [] and skipped == 0


def test_window_records_iso_weeks():
    # weeks=2 → 窗口起点周一 = 2026-08-03 - 7 天 = 2026-07-27
    records = [
        _rec("2026-07-26"),  # 窗口外（上一周周日）
        _rec("2026-07-27"),  # 窗口内（起点周一）
        _rec("2026-08-05"),  # 窗口内
    ]
    win = window_records(records, weeks=2, today=TODAY)
    assert [r["date"] for r in win] == ["2026-07-27", "2026-08-05"]


def test_aggregate_cross_day_sums():
    records = [
        _rec("2026-08-03", stage_hit=True,
             dirs={"samples": 2, "hits": 2, "hit_rate": 1.0}),
        _rec("2026-08-04", stage_hit=False,
             dirs={"samples": 2, "hits": 0, "hit_rate": 0.0}),
        _rec("2026-08-05", stage_hit=None, status="pending_maturity"),  # 不计
    ]
    stats = aggregate(records)
    assert stats["stage"] == {"rate": 0.5, "n": 2}
    assert stats["direction"] == {"rate": 0.5, "n": 4}


def test_weekly_breakdown_groups_by_monday():
    records = [
        _rec("2026-08-03", stage_hit=True, dirs={"samples": 1, "hits": 1}),
        _rec("2026-08-05", stage_hit=False, dirs={"samples": 1, "hits": 0}),
        _rec("2026-07-29", stage_hit=True, dirs={"samples": 2, "hits": 1}),
    ]
    weekly = weekly_breakdown(records)
    assert [w["week_start"].isoformat() for w in weekly] == ["2026-07-27", "2026-08-03"]
    assert weekly[0]["stage"] == {"rate": 1.0, "n": 1}
    assert weekly[1]["stage"] == {"rate": 0.5, "n": 2}
    assert weekly[1]["direction"] == {"rate": 0.5, "n": 2}


def _eight_week_records(stage_hit=True, dir_hits=2, dir_samples=2):
    """8 个连续自然周各一条已结算记录（2026-06-15 周一 ~ 2026-08-03 周）。"""
    from datetime import timedelta
    start = date(2026, 6, 15)
    return [
        _rec((start + timedelta(weeks=i) + timedelta(days=2)).isoformat(),
             stage_hit=stage_hit,
             dirs={"samples": dir_samples, "hits": dir_hits})
        for i in range(8)
    ]


def test_judge_graduated_when_8_weeks_above_lines():
    stats = aggregate(_eight_week_records())
    assert judge(stats, weeks=8, covered_weeks=8) == "graduated"


def test_judge_not_yet_when_below_line():
    stats = aggregate(_eight_week_records(stage_hit=False))
    assert judge(stats, weeks=8, covered_weeks=8) == "not_yet"


def test_judge_insufficient_when_fewer_weeks():
    stats = aggregate(_eight_week_records()[:7])
    assert judge(stats, weeks=8, covered_weeks=7) == "insufficient_data"


def test_judge_no_data():
    stats = aggregate([_rec("2026-08-05", status="pending_maturity")])
    assert judge(stats, weeks=8, covered_weeks=1) == "no_data"
