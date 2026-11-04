import copy
import json
from datetime import date, timedelta

import pytest

from investment_engine.qing_validation.records import build_record, record_path, save_record
from investment_engine.qing_validation.settle import settle_records
from qing_investment.kline_cache import init_db, save_index_klines, save_klines


TRADING_DAYS = [
    "2026-06-01",
    "2026-06-02",
    "2026-06-03",
    "2026-06-04",
    "2026-06-05",
    "2026-06-08",
    "2026-06-09",
]


def _bars(code, days, closes):
    return [
        {
            "code": code,
            "date": day,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 100,
            "turnover": 1.0,
            "amplitude": 0.0,
            "pct_change": 0.0,
        }
        for day, close in zip(days, closes)
    ]


def _market(db_path, days, stocks, benchmark=None):
    init_db(db_path=db_path)
    if benchmark is not None:
        save_index_klines(
            "sh000300",
            _bars("IDX000300", days, benchmark),
            db_path=db_path,
        )
    for code, closes in stocks.items():
        save_klines(code, _bars(code, days, closes), db_path=db_path)


def _config(config_dir, memberships):
    config_dir.mkdir()
    (config_dir / "stock_pool.yaml").write_text(
        json.dumps(
            {
                "stocks": [
                    {"code": code, "direction": direction}
                    for direction, code in memberships.items()
                ]
            }
        ),
        encoding="utf-8",
    )


def _direction(direction_id="final-direction", stock_code="000001", **overrides):
    item = {
        "direction_id": direction_id,
        "stock_code": stock_code,
        "horizon": "T+5",
        "polarity": "long",
        "invalidation": "跌破失效位",
    }
    item.update(overrides)
    return item


def _judgment(stage="震荡"):
    return {
        "data_as_of": "2026-06-01T07:00:00+08:00",
        "market_stage": stage,
        "direction": "测试方向",
        "horizon": "T+5",
        "trigger_conditions": ["触发"],
        "invalidation_conditions": ["失效"],
    }


def _record(record_id="record-1", *, day="2026-06-01", trigger=None, **overrides):
    kwargs = {
        "record_id": record_id,
        "trigger": trigger or {"id": "pre_market"},
        "generated_at": f"{day}T08:30:00+08:00",
        "data_as_of": f"{day}T07:00:00+08:00",
        "input_payload": {"record_id": record_id},
        "final_judgment": _judgment(),
        "raw_output": "冻结原文",
        "data_version": "data-v1",
        "rules_version": "rules-v1",
        "prompt_version": "prompt-v1",
    }
    kwargs.update(overrides)
    return build_record(**kwargs)


def _read(record, root):
    return json.loads(record_path(record, root=root).read_text(encoding="utf-8"))


def _items(record, root):
    return _read(record, root)["settlement"]["items"]


def _item(items, target_id, metric, target="final"):
    return next(
        item
        for item in items
        if item["target_id"] == target_id
        and item["metric"] == metric
        and item["target"] == target
    )


def test_t4_pending_t5_scored_with_real_sqlite_scorer(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 11, 11]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"final-direction": "000001"})
    record = _record(directions=[_direction()])
    save_record(record, root=root)

    settle_records("2026-06-05", root=root, config_dir=config_dir, db_path=db_path)
    pending = _items(record, root)
    assert [item["status"] for item in pending] == [
        "pending_maturity",
        "pending_maturity",
    ]
    assert all(item.get("hit") is None for item in pending)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)
    scored = _items(record, root)
    assert len(scored) == 2
    assert {(item["metric"], item["status"], item["hit"]) for item in scored} == {
        ("direction", "scored", True),
        ("stock", "scored", True),
    }
    assert all(item["record_id"] == "record-1" for item in scored)
    assert all(item["target"] == "final" and item["school"] is None for item in scored)
    assert all(item["target_id"] == "final-direction" for item in scored)
    assert _read(record, root)["status"] == "scored"

    path = record_path(record, root=root)
    first_bytes = path.read_bytes()
    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)
    assert path.read_bytes() == first_bytes
    assert len(_items(record, root)) == 2


def test_natural_days_cannot_replace_missing_trading_days(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    days = TRADING_DAYS[:5]
    _market(
        db_path,
        days,
        {"000001": [10] * len(days)},
        benchmark=[4000] * len(days),
    )
    _config(config_dir, {"final-direction": "000001"})
    record = _record(directions=[_direction()])
    save_record(record, root=root)

    settle_records("2026-06-30", root=root, config_dir=config_dir, db_path=db_path)

    assert {item["status"] for item in _items(record, root)} == {"pending_maturity"}


def test_final_and_expert_are_separate_and_protected_fields_stay_frozen(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {
            "000001": [10, 10, 10, 10, 10, 11, 11],
            "000002": [10, 10, 10, 10, 10, 9, 9],
        },
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(
        config_dir,
        {"final-direction": "000001", "expert-direction": "000002"},
    )
    record = _record(
        directions=[_direction()],
        expert_views=[
            _direction(
                "expert-direction",
                "000002",
                school="gator",
                view="专家原文",
            )
        ],
        review={"passed": True},
        citations={"patterns": ["pattern-1"]},
    )
    record["custom_frozen"] = {"keep": True}
    before = copy.deepcopy(record)
    save_record(record, root=root)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    saved = _read(record, root)
    items = saved["settlement"]["items"]
    assert len(items) == 4
    for metric in ("direction", "stock"):
        assert _item(items, "final-direction", metric)["hit"] is True
        expert = _item(items, "expert-direction", metric, target="expert")
        assert expert["hit"] is False
        assert expert["school"] == "gator"
    candidates = saved["attribution"]["candidates"]
    assert {(c["target"], c["school"], c["metric"]) for c in candidates} == {
        ("expert", "gator", "direction"),
        ("expert", "gator", "stock"),
    }
    for field, value in before.items():
        if field not in {"status", "settlement", "attribution", "stage_hit"}:
            assert saved[field] == value


def test_final_gate_does_not_disable_independent_expert(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 11, 11]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(
        config_dir,
        {"final-direction": "000001", "expert-direction": "000001"},
    )
    record = _record(
        final_judgment={},
        directions=[_direction()],
        expert_views=[_direction("expert-direction", school="qing")],
    )
    assert record["final_judgment"]["score_eligible"] is False
    save_record(record, root=root)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    items = _items(record, root)
    assert len(items) == 2
    assert {item["target"] for item in items} == {"expert"}
    assert {item["target_id"] for item in items} == {"expert-direction"}


def test_ineligible_and_non_t5_are_skipped_and_nonlong_is_not_applicable(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 11, 11]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"final-direction": "000001"})
    record = _record(
        directions=[
            _direction("short-direction", polarity="short"),
            _direction("neutral-direction", polarity="neutral"),
            _direction("wrong-horizon", horizon="T+1"),
            _direction("disabled-direction"),
        ]
    )
    record["directions"][-1]["score_eligible"] = False
    save_record(record, root=root)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    items = _items(record, root)
    assert len(items) == 4
    assert {item["target_id"] for item in items} == {
        "short-direction",
        "neutral-direction",
    }
    assert {item["status"] for item in items} == {"not_applicable"}
    assert all(item.get("hit") is None for item in items)
    assert _read(record, root)["attribution"]["candidates"] == []


@pytest.mark.parametrize("status", ["error", "missing"])
def test_error_and_missing_records_are_not_scored_or_rewritten(tmp_path, status):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 11, 11]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"final-direction": "000001"})
    record = _record(status=status, directions=[_direction()])
    record["directions"][0]["score_eligible"] = True
    save_record(record, root=root)
    path = record_path(record, root=root)
    before = path.read_bytes()

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    assert path.read_bytes() == before


def test_missing_members_and_missing_stock_are_independent(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 11, 11]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"mapped-direction": "000001"})
    unmapped = _record(
        "unmapped",
        directions=[_direction("unmapped-direction", "000001")],
    )
    missing_stock = _record(
        "missing-stock",
        directions=[_direction("mapped-direction", "999999")],
    )
    save_record(unmapped, root=root)
    save_record(missing_stock, root=root)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    unmapped_items = _items(unmapped, root)
    assert _item(unmapped_items, "unmapped-direction", "direction")["status"] == "insufficient_data"
    assert _item(unmapped_items, "unmapped-direction", "stock")["status"] == "scored"
    missing_items = _items(missing_stock, root)
    assert _item(missing_items, "mapped-direction", "direction")["status"] == "scored"
    assert _item(missing_items, "mapped-direction", "stock")["status"] == "insufficient_data"
    for record in (unmapped, missing_stock):
        saved = _read(record, root)
        assert saved["attribution"]["candidates"] == []
        assert all(item.get("hit") is not True for item in saved["settlement"]["items"] if item["status"] == "insufficient_data")


def test_missing_benchmark_makes_both_metrics_insufficient_without_candidates(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(db_path, TRADING_DAYS, {"000001": [10, 10, 10, 10, 10, 11, 11]})
    _config(config_dir, {"final-direction": "000001"})
    record = _record(directions=[_direction()])
    save_record(record, root=root)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    saved = _read(record, root)
    assert {item["status"] for item in saved["settlement"]["items"]} == {"insufficient_data"}
    assert all(item.get("hit") is None for item in saved["settlement"]["items"])
    assert saved["attribution"]["candidates"] == []


def test_strict_positive_excess_uses_scorer_epsilon(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 10.000000005, 10]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"final-direction": "000001"})
    record = _record(directions=[_direction()])
    save_record(record, root=root)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    items = _items(record, root)
    assert {item["status"] for item in items} == {"scored"}
    assert {item["hit"] for item in items} == {False}


def test_superseded_record_is_preserved_and_not_settled_again(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 11, 11]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"final-direction": "000001"})
    old = _record("old", directions=[_direction()])
    old_path = save_record(old, root=root)
    old_bytes = old_path.read_bytes()
    new = _record(
        "new",
        directions=[_direction()],
        supersedes_record_id="old",
    )
    save_record(new, root=root)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    assert old_path.read_bytes() == old_bytes
    assert len(_items(new, root)) == 2


def test_stage_hit_uses_truth_only_for_non_closing_reference(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    start = date(2026, 6, 1)
    days = [(start + timedelta(days=offset)).isoformat() for offset in range(32)]
    _market(
        db_path,
        days,
        {"000001": [10] * len(days)},
        benchmark=[4000] * len(days),
    )
    _config(config_dir, {})
    day = days[24]
    records = [
        _record("pre", day=day, final_judgment=_judgment("震荡")),
        _record(
            "intraday",
            day=day,
            trigger={"id": "intraday"},
            final_judgment=_judgment("主升"),
        ),
        _record(
            "closing",
            day=day,
            trigger={"id": "closing_review"},
            final_judgment=_judgment("震荡"),
        ),
    ]
    for record in records:
        save_record(record, root=root)

    settle_records(days[29], root=root, config_dir=config_dir, db_path=db_path)

    assert _read(records[0], root)["stage_hit"] is True
    intraday = _read(records[1], root)
    assert intraday["stage_hit"] is False
    assert intraday["attribution"]["candidates"] == []
    assert _read(records[2], root)["stage_hit"] == "not_applicable"


def test_atomic_replace_failure_keeps_frozen_file_and_removes_temp(tmp_path, monkeypatch):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 11, 11]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"final-direction": "000001"})
    record = _record(directions=[_direction()])
    path = save_record(record, root=root)
    before = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(
        "investment_engine.qing_validation.settle.os.replace",
        fail_replace,
    )
    with pytest.raises(OSError, match="injected replace failure"):
        settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    assert path.read_bytes() == before
    assert list(root.rglob("*.tmp")) == []


def test_all_insufficient_preserves_record_status_and_derives_settlement_status(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(db_path, TRADING_DAYS, {"000001": [10, 10, 10, 10, 10, 11, 11]})
    _config(config_dir, {"final-direction": "000001"})
    record = _record(directions=[_direction()])
    save_record(record, root=root)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    saved = _read(record, root)
    assert saved["status"] == "pending_maturity"
    assert saved["settlement"]["status"] == "insufficient_data"
    assert [item["status"] for item in saved["settlement"]["items"]] == [
        "insufficient_data",
        "insufficient_data",
    ]
    assert all(item.get("hit") is None for item in saved["settlement"]["items"])


def test_all_not_applicable_preserves_record_status_and_derives_settlement_status(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 11, 11]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"short-direction": "000001"})
    record = _record(directions=[_direction("short-direction", polarity="short")])
    save_record(record, root=root)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    saved = _read(record, root)
    assert saved["status"] == "pending_maturity"
    assert saved["settlement"]["status"] == "not_applicable"
    assert [item["status"] for item in saved["settlement"]["items"]] == [
        "not_applicable",
        "not_applicable",
    ]
    assert all(item.get("hit") is None for item in saved["settlement"]["items"])


def test_settle_rerun_preserves_reviewed_attribution_byte_for_byte(tmp_path):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 9, 9]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"final-direction": "000001"})
    record = _record(directions=[_direction()])
    path = save_record(record, root=root)
    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    saved = _read(record, root)
    candidate = saved["attribution"]["candidates"][0]
    candidate["status"] = "reviewed"
    candidate["reviewer"] = "human"
    candidate["review_items"][0]["evidence"] = [{"note": "人工核对完成"}]
    candidate["review_items"][0]["conclusion"] = "confirmed"
    saved["attribution"]["history"] = [{"event": "reviewed", "by": "human"}]
    path.write_text(
        json.dumps(saved, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    before = path.read_bytes()

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "stock_code",
    ["600000", "600000.SH", "sh600000", "1.600000", 600000],
)
def test_scoring_adapter_normalizes_accepted_stock_codes_without_mutating_frozen_value(
    tmp_path,
    stock_code,
):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"600000": [10, 10, 10, 10, 10, 11, 11]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"final-direction": "600000"})
    record = _record(directions=[_direction(stock_code=stock_code)])
    save_record(record, root=root)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    saved = _read(record, root)
    assert [item["status"] for item in saved["settlement"]["items"]] == [
        "scored",
        "scored",
    ]
    assert saved["directions"][0]["stock_code"] == stock_code


@pytest.mark.parametrize("missing", ["stock", "benchmark"])
def test_settlement_as_of_excludes_later_stock_and_benchmark_bars(tmp_path, missing):
    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    init_db(db_path=db_path)
    sparse_days = [day for day in TRADING_DAYS if day != "2026-06-08"]
    save_klines(
        "000999",
        _bars("000999", TRADING_DAYS, [10] * len(TRADING_DAYS)),
        db_path=db_path,
    )
    stock_days = sparse_days if missing == "stock" else TRADING_DAYS
    stock_closes = [10, 10, 10, 10, 10, 12] if missing == "stock" else [10, 10, 10, 10, 10, 11, 11]
    benchmark_days = sparse_days if missing == "benchmark" else TRADING_DAYS
    save_klines(
        "000001",
        _bars("000001", stock_days, stock_closes),
        db_path=db_path,
    )
    save_index_klines(
        "sh000300",
        _bars("IDX000300", benchmark_days, [4000] * len(benchmark_days)),
        db_path=db_path,
    )
    _config(config_dir, {"final-direction": "000001"})
    record = _record(directions=[_direction()])
    save_record(record, root=root)

    settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    saved = _read(record, root)
    assert saved["status"] == "pending_maturity"
    assert saved["settlement"]["status"] == "insufficient_data"
    assert [item["status"] for item in saved["settlement"]["items"]] == [
        "insufficient_data",
        "insufficient_data",
    ]


def test_external_review_edit_during_scoring_aborts_without_lost_update(
    tmp_path,
    monkeypatch,
):
    import investment_engine.qing_validation.settle as settle_module

    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 11, 11]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"final-direction": "000001"})
    record = _record(directions=[_direction()])
    path = save_record(record, root=root)
    original_direction_scores = settle_module.direction_scores
    interleaved = {}

    def edit_review_then_score(*args, **kwargs):
        external = json.loads(path.read_text(encoding="utf-8"))
        external["review"] = {"external_edit": True}
        external["attribution"] = {
            "candidates": [],
            "history": [{"event": "external_review"}],
        }
        path.write_text(
            json.dumps(external, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        interleaved["bytes"] = path.read_bytes()
        return original_direction_scores(*args, **kwargs)

    monkeypatch.setattr(settle_module, "direction_scores", edit_review_then_score)

    with pytest.raises(RuntimeError, match="concurrency"):
        settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    assert path.read_bytes() == interleaved["bytes"]
    assert list(root.rglob("*.tmp")) == []


def test_new_superseding_version_during_scoring_aborts_old_record_rewrite(
    tmp_path,
    monkeypatch,
):
    import investment_engine.qing_validation.settle as settle_module

    db_path = tmp_path / "klines.db"
    root = tmp_path / "records"
    config_dir = tmp_path / "config"
    _market(
        db_path,
        TRADING_DAYS,
        {"000001": [10, 10, 10, 10, 10, 11, 11]},
        benchmark=[4000] * len(TRADING_DAYS),
    )
    _config(config_dir, {"final-direction": "000001"})
    old = _record("old", directions=[_direction()])
    old_path = save_record(old, root=root)
    old_bytes = old_path.read_bytes()
    new = _record("new", directions=[_direction()], supersedes_record_id="old")
    new_path = record_path(new, root=root)
    original_direction_scores = settle_module.direction_scores
    interleaved = {}

    def supersede_then_score(*args, **kwargs):
        save_record(new, root=root)
        interleaved["new_bytes"] = new_path.read_bytes()
        return original_direction_scores(*args, **kwargs)

    monkeypatch.setattr(settle_module, "direction_scores", supersede_then_score)

    with pytest.raises(RuntimeError, match="concurrency"):
        settle_records("2026-06-08", root=root, config_dir=config_dir, db_path=db_path)

    assert old_path.read_bytes() == old_bytes
    assert new_path.read_bytes() == interleaved["new_bytes"]
    assert list(root.rglob("*.tmp")) == []
