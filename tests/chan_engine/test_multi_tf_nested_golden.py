"""M7-4 golden：512400 2026-08 spike 切片快照复现（设计 §7.3 / §1.1 锚）。

数据：tests/chan_engine/fixtures/mt512400_20260828.json（2026-08-28 收盘固化，
日线 262 + 60m/30m 各 260；分钟数据不可回填，ADR-005 口径快照）。
锚点 = 设计文档附录 A spike 记录（2026-08-28 三周期实证）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chan_engine.multi_tf import analyze_nested

FIXTURE = Path(__file__).parent / "fixtures" / "mt512400_20260828.json"


@pytest.fixture(scope="module")
def mtc():
    from chan_engine.data import load_daily  # noqa: F401  (fixture 自含，不触库)

    data = json.loads(FIXTURE.read_text())
    daily_dates = [r["trade_date"] for r in data["daily"]]
    from chan_engine.core.engine import RecursionEngine
    from chan_engine.spec.model import Bar

    daily_bars = [
        Bar(ts=i, o=r["open"], h=r["high"], l=r["low"], c=r["close"],
            vol=r["volume"] or 0.0)
        for i, r in enumerate(data["daily"])
    ]
    daily_chart = RecursionEngine().run(daily_bars)
    return analyze_nested(daily_chart, daily_dates,
                          {"60m": data["m60"], "30m": data["m30"]}), data


class TestDailyChart:
    def test_last_bi_is_spike_bi(self, mtc):
        """日线末端笔 = [7/20~8/11] up sure=False（spike：日线哑火锚）。"""
        chart, data = mtc
        last = chart.daily.bi[-1]
        assert (last.start_idx, last.end_idx) == (232, 248)
        assert last.dir.value == "up" and last.sure is False
        dates = [r["trade_date"] for r in data["daily"]]
        assert (dates[232], dates[248]) == ("2026-07-20", "2026-08-11")

    def test_daily_no_august_bsp(self, mtc):
        """spike：8 月无中枢无买卖点（日线哑火）。"""
        chart, data = mtc
        dates = [r["trade_date"] for r in data["daily"]]
        assert all(dates[b.idx] < "2026-08-01" for b in chart.daily.bsp)


class TestConfirm60m:
    def _conf(self, mtc):
        chart, _ = mtc
        return next(c for c in chart.confirmations
                    if c.tf == "60m" and c.bi_ref == (232, 248))

    def test_zs_in_bi_reproduces_spike(self, mtc):
        """笔内 60m 中枢 [1.712,1.851] 精确复现（spike 中枢区间）。"""
        c = self._conf(mtc)
        assert any(abs(z.zd - 1.712) < 1e-3 and abs(z.zg - 1.851) < 1e-3
                   for z in c.zs_in_bi), [(z.zd, z.zg) for z in c.zs_in_bi]

    def test_sell_point_l2_precise_location(self, mtc):
        """1 类卖点 L2 @8/11（区间套精确定位到 60m bar：10:30）。"""
        chart, data = mtc
        c = self._conf(mtc)
        sells = [b for b in c.bsp_in_bi if b.bstype == 1 and b.dir.value == "down"]
        assert sells, "笔内无次级别一卖"
        b = sells[0]
        assert b.level == 2
        assert data["m60"][b.idx]["dt"] == "2026-08-11 10:30"

    def test_backchi_true_and_dual_metric(self, mtc):
        """次级别背驰确认 + 双口径证据（MACD 主/Σ|Δc| 对照）。"""
        c = self._conf(mtc)
        assert c.backchi is True
        assert set(c.backchi_metric) == {"area_proxy", "macd_area"}
        for key in ("area_proxy", "macd_area"):
            assert c.backchi_metric[key]["enter"] > c.backchi_metric[key]["leave"] > 0

    def test_small_to_large_candidate(self, mtc):
        """日线同位置无背驰卖点 + 60m 一卖 → 小转大候选 True（课 43 标注纪律）。"""
        assert self._conf(mtc).small_to_large is True

    def test_coverage_and_second_buy(self, mtc):
        c = self._conf(mtc)
        assert c.coverage is True
        assert c.second_buy_confirmed is None  # 日线无二买候选关联


class TestSubCharts:
    def test_60m_third_buy_0819(self, mtc):
        """60m 三买 L1 @2026-08-19 15:00 价 1.864（spike 精确复现）。"""
        chart, data = mtc
        hit = [b for b in chart.sub["60m"].bsp
               if b.bstype == 3 and b.dir.value == "up"
               and data["m60"][b.idx]["dt"] == "2026-08-19 15:00"]
        assert hit and hit[0].level == 1
        assert abs(data["m60"][hit[0].idx]["close"] - 1.864) < 1e-9

    def test_30m_dual_level_first_buy_0819(self, mtc):
        """30m 一买 L1+L2 双级别共振 @2026-08-19 15:00 价 1.864（spike 精确复现）。"""
        chart, data = mtc
        hits = [b for b in chart.sub["30m"].bsp
                if b.bstype == 1 and b.dir.value == "up"
                and data["m30"][b.idx]["dt"] == "2026-08-19 15:00"]
        assert {b.level for b in hits} == {1, 2}
        assert abs(data["m30"][hits[0].idx]["close"] - 1.864) < 1e-9

    def test_30m_zs_reproduces_spike(self, mtc):
        """30m 中枢 [1.753,1.820] 与 [1.860,1.960] 复现。"""
        chart, _ = mtc
        zs30 = chart.sub["30m"].zs
        assert any(abs(z.zd - 1.753) < 1e-3 and abs(z.zg - 1.82) < 1e-3 for z in zs30)
        assert any(abs(z.zd - 1.860) < 1e-3 and abs(z.zg - 1.960) < 1e-3 for z in zs30)
