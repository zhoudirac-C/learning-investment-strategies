"""M7-5 Skill 接入层：report adapter 输出惯例测试（synthetic，不触网）。

口径依据：docs/design/chanlun-m7-multitimeframe-skill.md §8.2/§8.3 +
skills/finance/chanlun-structure-analysis/SKILL.md 输出惯例。
"""
from __future__ import annotations

import pytest

from chan_engine.multi_tf.model import MultiTimeframeChart, SubLevelConfirmation
from chan_engine.report import skill_adapter
from chan_engine.spec.model import (
    Bar, Bi, BSPoint, Direction, FX, NormalizedChart, Segment, ZhongShu,
)


def mkbar(i, h, l, c=None):
    return Bar(ts=i, o=(h + l) / 2, h=h, l=l, c=c if c is not None else (h + l) / 2, vol=1.0)


def zs(zd, zg, s, e, level=1):
    return ZhongShu(zd=zd, zg=zg, start_idx=s, end_idx=e, level=level)


def bsp(idx, t, d, level=1, bt=""):
    return BSPoint(idx=idx, bstype=t, dir=Direction(d), level=level, backchi_type=bt)


# ── 合成场景：日线 10 根 + 60m/30m 各 20 根 ──
# 日线：一买@4（trend_div）+ 二买@6；顶分型@8（前高 12.5）；底分型@4（低 9.5）
DAILY_DATES = [f"2026-08-{17 + i:02d}" for i in range(10)]
DAILY_BARS = [
    mkbar(0, 11.0, 10.5), mkbar(1, 10.8, 10.2), mkbar(2, 10.5, 10.0),
    mkbar(3, 10.2, 9.8), mkbar(4, 10.0, 9.5), mkbar(5, 10.6, 9.8),
    mkbar(6, 10.4, 9.9), mkbar(7, 11.0, 10.2), mkbar(8, 12.5, 11.0),
    mkbar(9, 12.2, 11.5, c=11.8),
]
DAILY = NormalizedChart(
    fx=[FX(idx=4, type=Direction.DOWN), FX(idx=8, type=Direction.UP)],
    bi=[Bi(0, 4, Direction.DOWN), Bi(4, 8, Direction.UP), Bi(8, 9, Direction.DOWN, sure=False)],
    zs=[zs(10.0, 10.6, 2, 5, level=2)],
    bsp=[bsp(4, 1, "up", level=2, bt="trend_div"), bsp(6, 2, "up", level=2)],
)

M60_BARS = [mkbar(i, 12.0, 11.8) for i in range(20)]
M60_BARS[15] = mkbar(15, 12.2, 11.60, c=11.60)  # 三买回试：低=收=11.60
M60_DTS = [f"2026-08-{24 + i // 4:02d} {['10:30', '11:30', '14:00', '15:00'][i % 4]}" for i in range(20)]
M30_BARS = [mkbar(i, 12.0, 11.8) for i in range(20)]
M30_BARS[16] = mkbar(16, 12.1, 11.55)  # 一买低 11.55
M30_DTS = [f"2026-08-2{4 + i // 4} 1{i % 4}:00" for i in range(20)]  # 简化 dt 标签

SUB60 = NormalizedChart(
    zs=[zs(11.7, 11.9, 5, 12)],
    bsp=[bsp(10, 1, "down", level=2, bt="consolidation_div"),  # 一卖（背驰标注）
         bsp(15, 3, "up")],                                    # 三买（入场点）
)
SUB30 = NormalizedChart(
    zs=[zs(11.65, 11.85, 6, 13)],
    bsp=[bsp(16, 1, "up", level=1, bt="trend_div")],           # 一买（入场点）
)


def make_mtc():
    return MultiTimeframeChart(
        daily=DAILY,
        sub={"60m": SUB60, "30m": SUB30},
        confirmations=[
            SubLevelConfirmation(bi_ref=(8, 9), tf="60m", bsp_in_bi=[SUB60.bsp[1]],
                                 backchi=False, coverage=True),
        ],
    )


def build():
    return skill_adapter.build_report(
        make_mtc(), code="sh512400",
        daily_bars=DAILY_BARS, daily_dates=DAILY_DATES,
        sub_bars={"60m": M60_BARS, "30m": M30_BARS},
        sub_stamps={"60m": M60_DTS, "30m": M30_DTS},
    )


class TestDefenseLines:
    def test_daily_defense_from_first_buy(self):
        """日线防守线 = 最近一买低点（图=日线，ref 带日期）。"""
        r = build()
        d = [x for x in r["defense_lines"] if x["level"] == "日线"]
        assert d and d[0]["price"] == 9.5
        assert "2026-08-21" in d[0]["ref"]

    def test_60m_defense_from_latest_buy_point(self):
        """60m 防守线 = 最近买入点（三买）回试低点，级别标注 60m。"""
        r = build()
        d = [x for x in r["defense_lines"] if x["level"] == "60m"]
        assert d and d[0]["price"] == 11.60
        assert "三买" in d[0]["ref"] and "2026-08-27 15:00" in d[0]["ref"]

    def test_defense_absent_when_no_buy_point(self):
        r = skill_adapter.build_report(
            MultiTimeframeChart(daily=NormalizedChart(), sub={}),
            code="x", daily_bars=DAILY_BARS, daily_dates=DAILY_DATES,
            sub_bars={}, sub_stamps={})
        assert r["defense_lines"] == []


class TestReversalConfirm:
    def test_daily_prior_high(self):
        """反转确认位 = 日线最近顶分型高（前高），级别=日线。"""
        r = build()
        assert r["reversal_confirm"]["price"] == 12.5
        assert r["reversal_confirm"]["level"] == "日线"
        assert "2026-08-25" in r["reversal_confirm"]["ref"]


class TestPositionNature:
    def test_trend_div_first_buy_is_reversal(self):
        """日线一买 backchi_type=trend_div → 反转仓（仅日线定性）。"""
        r = build()
        assert r["position_nature"]["label"] == "反转仓"
        assert r["position_nature"]["basis"] == "日线"

    def test_consolidation_div_is_rebound(self):
        daily = NormalizedChart(bsp=[bsp(4, 1, "up", bt="consolidation_div")])
        r = skill_adapter.build_report(
            MultiTimeframeChart(daily=daily, sub={}), code="x",
            daily_bars=DAILY_BARS, daily_dates=DAILY_DATES, sub_bars={}, sub_stamps={})
        assert r["position_nature"]["label"] == "反弹仓"

    def test_no_daily_first_buy_is_observe(self):
        r = skill_adapter.build_report(
            MultiTimeframeChart(daily=NormalizedChart(), sub={}), code="x",
            daily_bars=DAILY_BARS, daily_dates=DAILY_DATES, sub_bars={}, sub_stamps={})
        assert r["position_nature"]["label"] == "观察"

    def test_sub_level_never_decides_nature(self):
        """级别错配硬防线：60m 有一买也不改变日线定性（观察）。"""
        r = skill_adapter.build_report(
            MultiTimeframeChart(daily=NormalizedChart(), sub={"60m": SUB60}), code="x",
            daily_bars=DAILY_BARS, daily_dates=DAILY_DATES,
            sub_bars={"60m": M60_BARS}, sub_stamps={"60m": M60_DTS})
        assert r["position_nature"]["label"] == "观察"
        assert r["position_nature"]["basis"] == "日线"


class TestEntryPointsAndBackchi:
    def test_entry_points_with_level_tags(self):
        """入场点 = 当前日线笔内的次级别买点（价位+时刻+类型+图归属）。"""
        r = build()
        eps = {(e["level"], e["type"]) for e in r["entry_points"]}
        assert ("60m", "三买") in eps and ("30m", "一买") in eps
        e60 = next(e for e in r["entry_points"] if e["level"] == "60m")
        assert e60["price"] == 11.60 and e60["dt"] == "2026-08-27 15:00"

    def test_backchi_type_labeled(self):
        """背驰类型强制标注（逐级别）：60m 一卖=盘整背驰；日线一买=趋势背驰。"""
        r = build()
        assert r["backchi"]["60m"]["backchi_type"] == "consolidation_div"
        assert r["backchi"]["日线"]["backchi_type"] == "trend_div"
        assert r["backchi"]["30m"]["backchi_type"] == "trend_div"

    def test_backchi_empty_when_no_divergence(self):
        r = skill_adapter.build_report(
            MultiTimeframeChart(daily=NormalizedChart(), sub={}), code="x",
            daily_bars=DAILY_BARS, daily_dates=DAILY_DATES, sub_bars={}, sub_stamps={})
        assert r["backchi"] == {}


class TestInvalidation:
    def test_invalidation_lists(self):
        r = build()
        text = "\n".join(r["invalidation"])
        assert "11.6" in text and "60m" in text          # 破防守线（60m）
        assert "9.5" in text and "日线" in text           # 破日线防守
        assert "反弹" in text                             # 更大级别前低 → 反弹终结


class TestLevelCheckAndAsof:
    def test_level_check_three_questions(self):
        """级别归属三问自检：信号/防守/目标各属哪张图；仓位性质永远日线。"""
        r = build()
        lc = r["level_check"]
        assert lc["position_nature"] == "日线"
        assert set(lc) >= {"signal", "defense", "target", "position_nature"}

    def test_asof_marks_data_baseline(self):
        """报告必须标数据基准日（skill 纪律）。"""
        r = build()
        assert r["asof"]["daily"] == "2026-08-26"
        assert r["asof"]["60m"] == "2026-08-28 15:00"

    def test_window_note_declared(self):
        """分钟数据窗口能力边界声明（设计 §4.2：写进报告头）。"""
        r = build()
        assert "260" in r["window_note"]


class TestBspNaming:
    @pytest.mark.parametrize("t,d,name", [
        (1, "up", "一买"), (1, "down", "一卖"),
        (2, "up", "二买"), (2, "down", "二卖"),
        (3, "up", "三买"), (3, "down", "三卖"),
    ])
    def test_names(self, t, d, name):
        assert skill_adapter.bsp_name(bsp(0, t, d)) == name
