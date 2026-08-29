"""M7-5 golden：512400 端到端报告锚定（设计 §十一 M7-5 验收）。

链路：fixture 快照（mt512400_20260828.json）→ RecursionEngine → analyze_nested
→ skill_adapter.build_report。断言：防守线/入场点/背驰类型/级别标注正确。
数值锚 = 2026-08-29 管线实际输出，逐项目测核对与 spike 叙述一致后固化。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "mt512400_20260828.json"


@pytest.fixture(scope="module")
def report():
    from chan_engine.core.engine import RecursionEngine
    from chan_engine.multi_tf import analyze_nested
    from chan_engine.multi_tf.aligner import TFAligner
    from chan_engine.report.skill_adapter import build_report
    from chan_engine.spec.model import Bar

    data = json.loads(FIXTURE.read_text())

    def bundles(rows, key):
        bars = [Bar(ts=i, o=r["open"], h=r["high"], l=r["low"], c=r["close"],
                    vol=r["volume"] or 0.0) for i, r in enumerate(rows)]
        return bars, [r[key] for r in rows]

    dbars, ddates = bundles(data["daily"], "trade_date")
    daily_chart = RecursionEngine().run(dbars)
    sub_rows = {"60m": data["m60"], "30m": data["m30"]}
    mtc = analyze_nested(daily_chart, ddates, sub_rows)
    al = TFAligner(ddates, sub_rows)
    sub_bars, sub_stamps = {}, {}
    for tf in ("60m", "30m"):
        sub_bars[tf], sub_stamps[tf] = bundles(al.sub_rows[tf], "dt")
    return build_report(mtc, "sh512400", dbars, ddates, sub_bars, sub_stamps)


class TestDefenseAndReversal:
    def test_defense_60m_third_buy_low(self, report):
        d = next(x for x in report["defense_lines"] if x["level"] == "60m")
        assert d["price"] == 1.86
        assert "三买" in d["ref"] and "2026-08-19" in d["ref"]

    def test_defense_30m_second_buy_low(self, report):
        d = next(x for x in report["defense_lines"] if x["level"] == "30m")
        assert d["price"] == 1.87 and "二买" in d["ref"]

    def test_reversal_confirm_daily_prior_high(self, report):
        assert report["reversal_confirm"]["price"] == 2.029
        assert report["reversal_confirm"]["level"] == "日线"
        assert "2026-08-11" in report["reversal_confirm"]["ref"]


class TestPositionNatureAndBackchi:
    def test_position_nature_observe_daily_only(self, report):
        """日线无一买 → 观察（日线哑火的忠实翻译；次级别买点不改日线定性）。"""
        pn = report["position_nature"]
        assert pn["label"] == "观察" and pn["basis"] == "日线"

    def test_backchi_per_level_labeled(self, report):
        assert report["backchi"]["60m"]["backchi_type"] == "consolidation_div"
        assert "一卖@2026-08-11" in report["backchi"]["60m"]["ref"]
        assert report["backchi"]["30m"]["backchi_type"] == "consolidation_div"


class TestEntryPoints:
    def test_spike_entries_present(self, report):
        eps = {(e["level"], e["type"], e["price"], e["dt"]) for e in report["entry_points"]}
        assert ("60m", "三买", 1.864, "2026-08-19 15:00") in eps
        assert ("30m", "一买", 1.864, "2026-08-19 15:00") in eps
        assert ("30m", "二买", 1.873, "2026-08-25 11:00") in eps


class TestStatePlanAndLevelCheck:
    def test_60m_third_buy_confirmed(self, report):
        """60m：中枢上方 + 三买破坏确认（spike 三买 @8/19 的状态机翻译）。"""
        st = report["state_plan"]["60m"]
        assert st["position"] == "中枢上方"
        assert st["state"] == "破坏确认"

    def test_level_check(self, report):
        lc = report["level_check"]
        assert lc["position_nature"] == "日线"
        assert lc["target"] == "日线"
        assert "60m" in lc["signal"]

    def test_small_to_large_alert(self, report):
        assert any(a["tf"] == "60m" for a in report["small_to_large_alerts"])

    def test_asof_and_window_note(self, report):
        assert report["asof"]["daily"] == "2026-08-28"
        assert report["asof"]["60m"] == "2026-08-28 15:00"
        assert "260" in report["window_note"]

    def test_invalidation_with_levels(self, report):
        text = "\n".join(report["invalidation"])
        assert "1.86" in text and "60m" in text
        assert "日线前低" in text
