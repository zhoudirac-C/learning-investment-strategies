"""M7-5 G8/G9：同级别分解视角与分类状态→预案测试（设计 §8.3，L38/39 + P3 既定演进）。

G8 --decomp：选定级别输出 当前中枢 + 上一段/当前段 + 位置（机械化
"只做上涨+盘整段、回避下跌段"视角）。
G9 分类状态→预案：{中枢位置, 状态（延伸/新生候选/破坏确认）, 预案}，
状态判定绑 L18 定理三破坏几何（三买/三卖）。
"""
from __future__ import annotations

from chan_engine.report.skill_adapter import build_decomp, classify_state_plan
from chan_engine.spec.model import (
    Bar, BSPoint, Direction, NormalizedChart, Segment, ZhongShu,
)


def seg(s, e, d, sure=True):
    return Segment(start_bi=s, end_bi=e, dir=Direction(d), sure=sure)


def zs(zd, zg, s, e, level=1):
    return ZhongShu(zd=zd, zg=zg, start_idx=s, end_idx=e, level=level)


def bsp3(idx, d, level=1):
    return BSPoint(idx=idx, bstype=3, dir=Direction(d), level=level)


class TestBuildDecomp:
    def test_full(self):
        """当前中枢 + 上一段/当前段 + 位置（中枢上方）。"""
        chart = NormalizedChart(
            zs=[zs(10.0, 11.0, 2, 8)],
            seg=[seg(0, 2, "up"), seg(3, 5, "down"), seg(6, 8, "up", sure=False)],
        )
        d = build_decomp(chart, "60m", last_close=11.5)
        assert d["level"] == "60m"
        assert d["current_zs"] == {"zd": 10.0, "zg": 11.0}
        assert d["prev_segment"]["dir"] == "down"
        assert d["current_segment"]["dir"] == "up"
        assert d["current_segment"]["sure"] is False
        assert d["position"] == "中枢上方"

    def test_no_zs(self):
        chart = NormalizedChart(seg=[seg(0, 2, "up")])
        d = build_decomp(chart, "30m", last_close=10.0)
        assert d["current_zs"] is None and d["position"] == "无中枢"
        assert d["prev_segment"] is None  # 只有一段时无"上一段"

    def test_empty_chart(self):
        d = build_decomp(NormalizedChart(), "60m", last_close=1.0)
        assert d["current_zs"] is None and d["position"] == "无中枢"
        assert d["current_segment"] is None

    # ── G8 段序列重排视角（L38/39 机械化"只做上涨+盘整段"补全，2026-08-29） ──

    def test_segment_sequence_with_action_labels(self):
        """段序列重排：每段标参与/回避（上涨=参与, 下跌=回避, 盘整=观望）。"""
        chart = NormalizedChart(seg=[
            seg(0, 2, "up"),      # 上涨 → 参与
            seg(3, 5, "down"),     # 下跌 → 回避
            seg(6, 8, "up", sure=False),  # 未确认上涨 → 参与(待确认)
        ])
        d = build_decomp(chart, "60m", last_close=10.0)
        seq = d["segment_sequence"]
        assert len(seq) == 3
        assert seq[0] == {"dir": "up", "sure": True, "action": "参与"}
        assert seq[1] == {"dir": "down", "sure": True, "action": "回避"}
        assert seq[2] == {"dir": "up", "sure": False, "action": "参与(待确认)"}

    def test_segment_sequence_empty_chart(self):
        """空图 → 段序列为空列表。"""
        d = build_decomp(NormalizedChart(), "60m", last_close=1.0)
        assert d["segment_sequence"] == []


class TestClassifyStatePlan:
    """分类状态→预案（G9）：位置 × 状态 → 可操作预案。"""

    ZS = zs(10.0, 11.0, 2, 8)

    def test_in_zs_extension(self):
        """中枢内 → 延伸：中枢内无该级别买卖点，等方向选择。"""
        chart = NormalizedChart(zs=[self.ZS])
        st = classify_state_plan(chart, last_close=10.5, level="60m")
        assert st["position"] == "中枢内"
        assert st["state"] == "延伸"
        assert "等" in st["plan"]

    def test_above_zs_new_candidate(self):
        """中枢上方且无三买 → 新生候选：等回试确认。"""
        chart = NormalizedChart(zs=[self.ZS])
        st = classify_state_plan(chart, last_close=11.5, level="60m")
        assert st["position"] == "中枢上方"
        assert st["state"] == "新生候选"
        assert "回试" in st["plan"] and "三买" in st["plan"]

    def test_above_zs_third_buy_confirmed(self):
        """中枢上方 + 三买已出（L18 定理三破坏确认）→ 破坏确认：持有到新高预案。"""
        chart = NormalizedChart(zs=[self.ZS], bsp=[bsp3(10, "up")])
        st = classify_state_plan(chart, last_close=11.5, level="60m")
        assert st["state"] == "破坏确认"
        assert "持有" in st["plan"]

    def test_below_zs_third_sell_confirmed(self):
        """中枢下方 + 三卖已出 → 破坏确认（向下）：回避/退出预案。"""
        chart = NormalizedChart(zs=[self.ZS], bsp=[bsp3(10, "down")])
        st = classify_state_plan(chart, last_close=9.5, level="60m")
        assert st["position"] == "中枢下方"
        assert st["state"] == "破坏确认"
        assert "退出" in st["plan"] or "回避" in st["plan"]

    def test_below_zs_no_sell(self):
        """中枢下方无三卖 → 新生候选（向下）：不抄底，等一买。"""
        chart = NormalizedChart(zs=[self.ZS])
        st = classify_state_plan(chart, last_close=9.5, level="60m")
        assert st["state"] == "新生候选"
        assert "一买" in st["plan"]

    def test_no_zs(self):
        st = classify_state_plan(NormalizedChart(), last_close=1.0, level="日线")
        assert st["position"] == "无中枢"
        assert st["state"] == "无结构"

    def test_third_buy_before_zs_end_not_counted(self):
        """三买必须落在中枢结束之后（时序纪律）。"""
        chart = NormalizedChart(zs=[self.ZS], bsp=[bsp3(5, "up")])  # idx5 < zs.end 8
        st = classify_state_plan(chart, last_close=11.5, level="60m")
        assert st["state"] == "新生候选"  # 中枢内的"三买"不算破坏确认
