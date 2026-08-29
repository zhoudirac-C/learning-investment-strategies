"""M7-4 区间套递归层：nested 归属逻辑与四输出测试（synthetic，stub 引擎隔离）。

口径依据：docs/design/chanlun-m7-multitimeframe-skill.md §7 + §5.2；
归属策略实证修正见 docs/tasks/chanlun-m7-4-nested.md（全序列引擎+窗口归属）。
"""
from __future__ import annotations

import pytest

from chan_engine.multi_tf import model, nested
from chan_engine.spec.model import Bar, Bi, BSPoint, Direction, NormalizedChart, ZhongShu

DAILY_DATES = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]

# 60m 每日 4 根（10:30/11:30/14:00/15:00）；30m 每日 8 根
L60 = ["10:30", "11:30", "14:00", "15:00"]
L30 = ["10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"]


def make_rows(dates=DAILY_DATES, labels=L60, complete=1):
    rows = []
    for d in dates:
        for hm in labels:
            rows.append({"dt": f"{d} {hm}", "open": 1.0, "high": 1.1, "low": 0.9,
                         "close": 1.0, "volume": 100.0, "complete": complete})
    return rows


class StubEngine:
    """罐头引擎：返回预置 NormalizedChart（记录收到的 bars 供断言）。"""

    def __init__(self, chart):
        self.chart = chart
        self.seen_bars = None

    def run(self, bars):
        self.seen_bars = bars
        return self.chart


def bi(s, e, d="up"):
    return Bi(start_idx=s, end_idx=e, dir=Direction(d))


def bsp(idx, t, d, level=1, sure=True, bt=""):
    return BSPoint(idx=idx, bstype=t, dir=Direction(d), level=level, sure=sure,
                   backchi_type=bt)


def zs(zd, zg, s, e, level=1):
    return ZhongShu(zd=zd, zg=zg, start_idx=s, end_idx=e, level=level)


def run_nested(daily_chart, charts60=None, charts30=None, rows60=None, rows30=None,
               daily_dates=DAILY_DATES):
    """charts60/charts30: 罐头 sub 图；rows 缺省为全覆盖合成行。"""
    stubs = {}
    rows = {}
    if rows60 is not None or charts60 is not None:
        rows["60m"] = rows60 if rows60 is not None else make_rows(labels=L60)
        stubs["60m"] = StubEngine(charts60 or NormalizedChart())
    if rows30 is not None or charts30 is not None:
        rows["30m"] = rows30 if rows30 is not None else make_rows(labels=L30)
        stubs["30m"] = StubEngine(charts30 or NormalizedChart())
    mtc = nested.analyze_nested(daily_chart, daily_dates, rows,
                                engine_factory=lambda tf: stubs[tf])
    return mtc, stubs


class TestAttribution:
    """窗口归属：zs span 相交即归入；bsp 按 idx 落窗。"""

    def test_zs_intersect_and_bsp_in_window(self):
        daily = NormalizedChart(bi=[bi(0, 2), bi(2, 4, "down")])
        # 60m：20 根（5 天×4）；bi0 窗 = pos 0..12，bi1 窗 = pos 8..20
        chart60 = NormalizedChart(
            zs=[zs(1.0, 1.1, 2, 6), zs(1.2, 1.3, 14, 18), zs(1.4, 1.5, 10, 14)],
            bsp=[bsp(3, 1, "down"), bsp(15, 1, "up")],
        )
        mtc, _ = run_nested(daily, charts60=chart60)
        c60 = [c for c in mtc.confirmations if c.tf == "60m"]
        c0 = next(c for c in c60 if c.bi_ref == (0, 2))
        c1 = next(c for c in c60 if c.bi_ref == (2, 4))
        assert [(z.start_idx, z.end_idx) for z in c0.zs_in_bi] == [(2, 6), (10, 14)]
        assert [(z.start_idx, z.end_idx) for z in c1.zs_in_bi] == [(10, 14), (14, 18)]
        assert [b.idx for b in c0.bsp_in_bi] == [3]
        assert [b.idx for b in c1.bsp_in_bi] == [15]
        assert c0.coverage is True and c1.coverage is True

    def test_coverage_false_propagates(self):
        """次级别数据不足 → coverage=False + note 透传（禁止静默降级）。"""
        daily = NormalizedChart(bi=[bi(0, 2), bi(2, 4, "down")])
        rows = make_rows(dates=DAILY_DATES[2:], labels=L60)  # 只覆盖 D3 起
        mtc, _ = run_nested(daily, charts60=NormalizedChart(), rows60=rows)
        c0 = next(c for c in mtc.confirmations if c.tf == "60m" and c.bi_ref == (0, 2))
        c1 = next(c for c in mtc.confirmations if c.tf == "60m" and c.bi_ref == (2, 4))
        assert c0.coverage is False and "次级别数据不足" in c0.note
        assert c1.coverage is True

    def test_partial_bars_never_reach_engine(self):
        """complete=0 未收盘 bar 不进入次级别引擎（§4.3 纪律在 M7-4 管线的落实）。"""
        rows = make_rows(labels=L60)
        rows.append({"dt": "2026-08-29 10:30", "open": 1.0, "high": 1.1, "low": 0.9,
                     "close": 1.0, "volume": 1.0, "complete": 0})
        mtc, stubs = run_nested(NormalizedChart(bi=[bi(0, 2)]), charts60=NormalizedChart(),
                                rows60=rows)
        assert len(stubs["60m"].seen_bars) == 20  # 21 行 → 剔除 1 根未完成

    def test_empty_sub_rows(self):
        """某 tf 完全无数据：sub 图为空、confirmation coverage=False，不崩。"""
        daily = NormalizedChart(bi=[bi(0, 2)])
        mtc, _ = run_nested(daily, charts60=NormalizedChart(), rows60=[])
        c0 = mtc.confirmations[0]
        assert c0.coverage is False and c0.zs_in_bi == [] and c0.bsp_in_bi == []


class TestBackchiAndSmallToLarge:
    def test_backchi_requires_opposite_dir_type1(self):
        """次级别背驰 = 窗口内反向 bstype=1（笔末端反转信号）。"""
        daily = NormalizedChart(bi=[bi(0, 2)])  # 上行笔
        chart60 = NormalizedChart(bsp=[bsp(3, 1, "down")])  # 反向一卖 → 背驰确认
        mtc, _ = run_nested(daily, charts60=chart60)
        assert mtc.confirmations[0].backchi is True

        chart60_same = NormalizedChart(bsp=[bsp(3, 1, "up")])  # 同向 → 不算
        mtc2, _ = run_nested(daily, charts60=chart60_same)
        assert mtc2.confirmations[0].backchi is False

        chart60_t3 = NormalizedChart(bsp=[bsp(3, 3, "up")])  # 三类 → 不算
        mtc3, _ = run_nested(daily, charts60=chart60_t3)
        assert mtc3.confirmations[0].backchi is False

    def test_small_to_large_candidate(self):
        """小转大（课 43）：次级别背驰 + 日线同位置无一买/一卖 → 候选 True。"""
        daily = NormalizedChart(bi=[bi(0, 2)])  # 日线无 bsp
        chart60 = NormalizedChart(bsp=[bsp(3, 1, "down")])
        mtc, _ = run_nested(daily, charts60=chart60)
        assert mtc.confirmations[0].small_to_large is True

    def test_no_small_to_large_when_daily_resonates(self):
        """日线同位置已有背驰买卖点 → 共振而非小转大 → False。"""
        daily = NormalizedChart(bi=[bi(0, 2)], bsp=[bsp(2, 1, "down")])  # 日线一卖 @bi 末端
        chart60 = NormalizedChart(bsp=[bsp(3, 1, "down")])
        mtc, _ = run_nested(daily, charts60=chart60)
        assert mtc.confirmations[0].small_to_large is False

    def test_no_backchi_no_small_to_large(self):
        daily = NormalizedChart(bi=[bi(0, 2)])
        mtc, _ = run_nested(daily, charts60=NormalizedChart())
        assert mtc.confirmations[0].small_to_large is False

    # ── G10 小转大必要条件检查（L44 两步走第一步，2026-08-29） ──
    # 次级别背驰 + 最后次级别中枢出三类买卖点 → 必要条件满足
    # 次级别背驰 + 最后中枢无三类买卖点 → 必要条件不满足（正常震荡，不传导）

    def test_s2l_premise_met_with_three_sell(self):
        """小转大必要条件满足：次级别一卖 + 窗口内中枢之后有三卖。"""
        daily = NormalizedChart(bi=[bi(0, 2)])  # 日线无 bsp
        chart60 = NormalizedChart(
            zs=[zs(1.0, 1.1, 2, 6)],
            bsp=[bsp(3, 1, "down"),     # 一卖（背驰确认）
                 bsp(7, 3, "down")],    # 三卖（中枢之后）
        )
        mtc, _ = run_nested(daily, charts60=chart60)
        c = mtc.confirmations[0]
        assert c.small_to_large is True
        assert "必要条件满足" in c.s2l_premise

    def test_s2l_premise_not_met_no_three_bsp(self):
        """小转大必要条件不满足：次级别背驰但最后中枢无三类买卖点。"""
        daily = NormalizedChart(bi=[bi(0, 2)])
        chart60 = NormalizedChart(
            zs=[zs(1.0, 1.1, 2, 6)],
            bsp=[bsp(3, 1, "down")],   # 只有一卖，无三卖
        )
        mtc, _ = run_nested(daily, charts60=chart60)
        c = mtc.confirmations[0]
        # small_to_large 仍为 True（候选），但 premise 标注必要条件不满足
        assert c.small_to_large is True
        assert "必要条件不满足" in c.s2l_premise

    def test_s2l_premise_empty_when_no_candidate(self):
        """无小转大候选时 premise 为空。"""
        daily = NormalizedChart(bi=[bi(0, 2)], bsp=[bsp(2, 1, "down")])
        chart60 = NormalizedChart(bsp=[bsp(3, 1, "down")])
        mtc, _ = run_nested(daily, charts60=chart60)
        c = mtc.confirmations[0]
        assert c.small_to_large is False
        assert c.s2l_premise == ""


class TestSecondBuyConfirmation:
    """二买=次级别一买确认（买点定律 claim-20061205-001-a）。日线 bi1(2,4) 为回调笔，
    其末端（daily idx 4）挂日线二买候选；60m 窗 pos 8..20，末段 = idx≥16。"""

    DAILY = NormalizedChart(
        bi=[bi(0, 2), bi(2, 4, "down")],
        bsp=[bsp(2, 1, "up", level=2, bt="trend_div"),  # 一买 @2
             bsp(4, 2, "up", level=2)],                  # 二买候选 @4（回调笔末端）
    )

    def test_confirmed_true(self):
        chart60 = NormalizedChart(bsp=[bsp(18, 1, "up")])  # 末段次级别一买
        mtc, _ = run_nested(self.DAILY, charts60=chart60)
        c1 = next(c for c in mtc.confirmations if c.tf == "60m" and c.bi_ref == (2, 4))
        assert c1.second_buy_confirmed is True

    def test_unconfirmed_false(self):
        """次级别无一买 → False（M7-5 报告层据此标 sure=False）。"""
        chart60 = NormalizedChart(bsp=[bsp(18, 3, "up")])  # 三买不算
        mtc, _ = run_nested(self.DAILY, charts60=chart60)
        c1 = next(c for c in mtc.confirmations if c.tf == "60m" and c.bi_ref == (2, 4))
        assert c1.second_buy_confirmed is False

    def test_type1_outside_tail_not_counted(self):
        """一买在窗口前段（非末段）→ 不构成对末端二买的确认。"""
        chart60 = NormalizedChart(bsp=[bsp(9, 1, "up")])  # idx 9 < 16
        mtc, _ = run_nested(self.DAILY, charts60=chart60)
        c1 = next(c for c in mtc.confirmations if c.tf == "60m" and c.bi_ref == (2, 4))
        assert c1.second_buy_confirmed is False

    def test_no_daily_second_buy_none(self):
        c0 = None
        chart60 = NormalizedChart(bsp=[bsp(18, 1, "up")])
        mtc, _ = run_nested(self.DAILY, charts60=chart60)
        c0 = next(c for c in mtc.confirmations if c.tf == "60m" and c.bi_ref == (0, 2))
        assert c0.second_buy_confirmed is None

    def test_30m_tail_window(self):
        """30m 末段 = 最后 8 根（240//30）。"""
        chart30 = NormalizedChart(bsp=[bsp(26, 1, "up")])  # 30m 窗 16..40，末段 ≥32
        mtc, _ = run_nested(self.DAILY, charts30=chart30)
        c1 = next(c for c in mtc.confirmations if c.tf == "30m" and c.bi_ref == (2, 4))
        assert c1.second_buy_confirmed is False  # 26 不在末段
        chart30b = NormalizedChart(bsp=[bsp(33, 1, "up")])
        mtc2, _ = run_nested(self.DAILY, charts30=chart30b)
        c1b = next(c for c in mtc2.confirmations if c.tf == "30m" and c.bi_ref == (2, 4))
        assert c1b.second_buy_confirmed is True


class TestContainer:
    def test_chart_assembly(self):
        daily = NormalizedChart(bi=[bi(0, 2), bi(2, 4, "down")])
        mtc, _ = run_nested(daily, charts60=NormalizedChart(), charts30=NormalizedChart())
        assert mtc.daily is daily
        assert set(mtc.sub) == {"60m", "30m"}
        assert len(mtc.slices) == 4   # 2 笔 × 2 tf
        assert len(mtc.confirmations) == 4
        assert all(isinstance(c, model.SubLevelConfirmation) for c in mtc.confirmations)
