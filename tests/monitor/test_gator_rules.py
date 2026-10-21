"""鳄鱼派确定性规则引擎单测（P2b）。

设计文档：docs/design/dual-school-architecture.md
规则来源：sources/third_party/gator-method/03-规则体系/
"""

from __future__ import annotations

from qing_investment.monitor.rules.gator_rules import (
    GatorAssessment,
    HedgeLevel,
    SignalLevel,
    assess_emotion_ice,
    assess_hedge,
    assess_scissors,
    assess_stop_falling,
)


class TestStopFalling:
    def test_all_signals_met(self):
        """5 信号全满足 → 保守可出手。"""
        a = assess_stop_falling(
            market={"sh_pct": 0.8, "cyb_pct": 1.2, "hs300_pct": 0.9, "zz2000_pct": 1.3},
            sector={"top_sector_name": "AI", "top_sector_pct": 2.1, "top_sector_red_ratio": 0.82},
            broker={"limit_up_count": 2},
            fund={"volume_ratio": 1.35, "north_net_inflow": 42.0},
            basis={"basis_delta": -3.2, "index_up": True},  # 贴水且上涨 → met
        )
        assert isinstance(a, GatorAssessment)
        assert a.met_count == 5
        assert a.stance == "保守选手可出手"

    def test_three_signals_aggressive(self):
        """恰好 3 个满足 → 激进可出手（保守不行）。"""
        a = assess_stop_falling(
            market={"sh_pct": 0.1, "cyb_pct": 2.5, "hs300_pct": 0.2, "zz2000_pct": 1.9},  # 不共振
            sector={"top_sector_name": "AI", "top_sector_pct": 2.1, "top_sector_red_ratio": 0.82},  # met
            broker={"limit_up_count": 1},  # met
            fund={"volume_ratio": 1.5},  # met
            basis={"basis_delta": 1.0, "index_up": True},  # 升水不算
        )
        assert a.met_count == 3
        assert a.stance == "激进选手可出手"

    def test_two_signals_wait(self):
        """2 个满足 → 继续观望。"""
        a = assess_stop_falling(
            market={"sh_pct": 0.5, "cyb_pct": 0.8, "hs300_pct": 0.6, "zz2000_pct": 0.9},  # 收敛 met
            sector={"top_sector_name": "AI", "top_sector_pct": 0.1, "top_sector_red_ratio": 0.4},
            broker={"limit_up_count": 0},
            fund={"volume_ratio": 1.5},
            basis={"basis_delta": -1.0, "index_up": False},  # 下跌途中贴水缩小不算
        )
        assert a.met_count == 2
        assert a.stance == "继续观望"

    def test_missing_data_not_counted(self):
        """数据缺失计 UNKNOWN，不计入满足数也不 crash。"""
        a = assess_stop_falling()
        assert a.met_count == 0
        assert all(s.level == SignalLevel.UNKNOWN for s in a.signals)
        assert a.stance == "继续观望"
        assert any("缺失" in n for n in a.notes)

    def test_basis_shrink_during_drop_not_valid(self):
        """基差在下跌途中缩小 → 不算（第一章明确）。"""
        a = assess_stop_falling(basis={"basis_delta": -2.0, "index_up": False})
        basis_sig = next(s for s in a.signals if s.rule_id.endswith("basis"))
        assert basis_sig.level == SignalLevel.NOT_MET
        assert "下跌途中缩小不算" in basis_sig.detail


class TestEmotionIce:
    def test_ice_met(self):
        s = assess_emotion_ice(-3.5, 45, -2.3)
        assert s.level == SignalLevel.MET

    def test_one_condition_missing_fails(self):
        # 跌停只有 20 家 → 不满足
        s = assess_emotion_ice(-3.5, 20, -2.3)
        assert s.level == SignalLevel.NOT_MET

    def test_boundary_exact_thresholds(self):
        # 微盘 -3.0（含）、跌停 31（>30）、上证 -2.01（<-2）
        s = assess_emotion_ice(-3.0, 31, -2.01)
        assert s.level == SignalLevel.MET

    def test_missing_data(self):
        s = assess_emotion_ice(None, 45, -2.3)
        assert s.level == SignalLevel.UNKNOWN


class TestScissors:
    def test_no_divergence(self):
        s = assess_scissors(0.3, 0.5)
        assert s.level == SignalLevel.NOT_MET

    def test_light_divergence(self):
        s = assess_scissors(1.0, 0.4)  # diff 0.6
        assert s.level == SignalLevel.MET
        assert "存在分歧" in s.detail

    def test_heavy_divergence(self):
        s = assess_scissors(0.2, 1.5)  # diff 1.3
        assert "分歧较重" in s.detail

    def test_severe_divergence(self):
        s = assess_scissors(-0.5, 2.0)  # diff 2.5
        assert "分歧严重" in s.detail

    def test_missing(self):
        assert assess_scissors(None, 1.0).level == SignalLevel.UNKNOWN


class TestHedge:
    def test_large_hedge(self):
        sig, lvl = assess_hedge(all_etf_up=True, policy_meeting=True, broad_etf_up=True)
        assert lvl == HedgeLevel.LARGE
        assert sig.level == SignalLevel.MET

    def test_medium_hedge(self):
        _, lvl = assess_hedge(broad_etf_up=True)
        assert lvl == HedgeLevel.MEDIUM

    def test_small_hedge(self):
        _, lvl = assess_hedge(big_finance_up=True)
        assert lvl == HedgeLevel.SMALL

    def test_none(self):
        _, lvl = assess_hedge(big_finance_up=False, broad_etf_up=False, all_etf_up=False)
        assert lvl == HedgeLevel.NONE

    def test_hedge_not_stop_falling_note(self):
        """上涨由护盘驱动 ≠ 止跌（第十二章配套规则）。"""
        sig, _ = assess_hedge(big_finance_up=True)
        assert "护盘驱动 ≠ 止跌" in sig.detail
