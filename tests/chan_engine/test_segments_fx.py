"""M7-6 G5：特征序列线段构造器（core/segments_fx.py）测试。

口径：课 65/67/71/78（ADR-003 口径 A、ADR-004 古怪延续、ADR-012 双轨方案 C）。
锚：SEG-001~005 expect（课文手工口径）+ 合并/分型/缺口单元用例。
"""
from __future__ import annotations

import pytest

from chan_engine.core.segments_fx import build_fx_segments
from chan_engine.spec.case_io import load_case
from chan_engine.spec.model import Bi, Direction


def bi(s, e, d, sure=True):
    return Bi(start_idx=s, end_idx=e, dir=Direction(d), sure=sure)


def seg_expect(case_id):
    case = load_case(f"src/chan_engine/spec/cases/{case_id}.yaml")
    bi_list = [Bi(start_idx=b["start_idx"], end_idx=b["end_idx"],
                  dir=Direction(b["dir"]), sure=b["sure"])
               for b in case.expect["bi"]]
    return bi_list, case.bars, case.expect["seg"]


def run(case_id):
    bi_list, bars, expect_seg = seg_expect(case_id)
    segs = build_fx_segments(bi_list, bars)
    got = [(s.start_bi, s.end_bi, s.dir.value, s.sure) for s in segs]
    want = [(s["start_bi"], s["end_bi"], s["dir"], s["sure"]) for s in expect_seg]
    return got, want


class TestSpecCases:
    """课文口径锚（seg 表逐字段比对）。"""

    def test_seg001_no_gap_up(self):
        """情况 1 无缺口：顶分型成立即终结（seg0 = bi0..bi 2 up）。"""
        got, want = run("seg-001")
        assert got == want

    def test_seg002_no_gap_down(self):
        """情况 1 对称（向下线段，底分型终结）。"""
        got, want = run("seg-002")
        assert got == want

    def test_seg003_gap_reverse_confirm(self):
        """情况 2 有缺口：反向三笔破位才确认（课 71）。"""
        got, want = run("seg-003")
        assert got == want

    def test_seg004_single_bi_no_break(self):
        """单纯一笔不破坏线段（课 65）：全程一段 sure=False。"""
        got, want = run("seg-004")
        assert got == want

    def test_seg005_quirky_segment_continuation(self):
        """古怪线段（课 78）：第一种情况笔破坏未发展成线段破坏 → 延续。"""
        got, want = run("seg-005")
        assert got == want

    def test_seg005_standardized_range(self):
        """课 78 标准化：段端点非极值时区间取实际极值（SEG-005 高点 21 在 bi3，
        非起点 20；低点 12 在终点 bi8）——seg 表只钉结构，区间包络在此钉住。"""
        bi_list, bars, _ = seg_expect("seg-005")
        segs = build_fx_segments(bi_list, bars)
        assert (segs[0].high, segs[0].low) == (21.0, 12.0)


class TestMechanics:
    """机制单元：构造精确笔序直接测 build_fx_segments。

    通用骨架（笔端点 pivot 逐笔交替）：
      up 段 bi0(0→2 高10)、bi1(2→4 低6)、bi2(4→6 高12)、bi3(6→8 低8)…
    bars 仅需端点极值可读（_elem_range 只读端点 h/l）。
    """

    def _bars(self, pivots):
        """pivot 价格序列 → bars（每 pivot 一根 bar，h/l=该点价格）。"""
        from chan_engine.spec.builders import bars_from_ohlc
        return bars_from_ohlc([(p, p, p, p) for p in pivots])

    def test_minimal_segment_sure_false_at_tail(self):
        # 单纯上行三笔，无反向特征序列分型 → 一段未完（未被破坏 → sure=False，
        # 即使三笔全 sure：段终结必须右侧确认，与五表纪律一致）
        bars = self._bars([5, 5, 10, 10, 7, 7, 12, 12])
        segs = build_fx_segments([bi(0, 2, "up"), bi(2, 4, "down"), bi(4, 6, "up")], bars)
        assert len(segs) == 1
        assert (segs[0].start_bi, segs[0].end_bi, segs[0].dir.value) == (0, 2, "up")
        assert segs[0].sure is False

    def test_absorb_merge_raises_low(self):
        """末元素包含新笔 → 吸收（向上线段取 max/max，课 71 + chanpy EigenFX）。

        X2=bi3[9,11] 吸收 bi5[9.6,10.8] 后 low 抬到 9.6；唯因如此
        X3=bi7[9.2,10.9] 的 low(9.2) < X2.low(9.6)，顶分型才成立（情况 1 无缺口
        → seg0=bi0..bi2）。不吸收则 X2.low=9 < 9.2 无分型、全程一段——本用例
        据此钉住吸收语义。
        """
        bars = self._bars([5, 5, 10, 10, 7, 7, 11, 11, 9, 9,
                           10.8, 10.8, 9.6, 9.6, 10.9, 10.9, 9.2, 9.2])
        bis = [bi(0, 2, "up"), bi(2, 4, "down"), bi(4, 6, "up"), bi(6, 8, "down"),
               bi(8, 10, "up"), bi(10, 12, "down"), bi(12, 14, "up"), bi(14, 16, "down")]
        got = [(s.start_bi, s.end_bi, s.dir.value, s.sure)
               for s in build_fx_segments(bis, bars)]
        assert got == [(0, 2, "up", True), (3, 7, "down", False)]

    def test_excluded_bi_not_merged(self):
        """末元素被新笔包含 → 不合并、新开元素（excluded，课 71/chanpy）。

        bi5[6,14] 包含 X2=bi3[8,12] → X2 不合并，X3=bi5 新开；之后 bi7/9/11
        均被 X3 吸收，窗口不再推进 → 全程一段。若错误合并（X2 变 [8,14]），
        bi7=[7,13] 会成为 X3 并与 X1/X2 构成顶分型 → 错误切出 seg0=bi0..bi4。
        """
        bars = self._bars([5, 5, 10, 10, 7, 7, 12, 12, 8, 8, 14, 14, 6, 6,
                           13, 13, 7, 7, 11, 11, 8, 8, 12, 12, 9, 9])
        bis = [bi(2 * k, 2 * k + 2, "up" if k % 2 == 0 else "down")
               for k in range(12)]
        got = [(s.start_bi, s.end_bi, s.dir.value, s.sure)
               for s in build_fx_segments(bis, bars)]
        assert got == [(0, 11, "up", False)]

    def test_gap_pending_tail_unsure(self):
        """情况 2 候选到数据末尾未确认 → 段收于候选点 sure=False（课 67/71）。

        X1=bi1[7,10]、X2=[11.8,13]（bi3 吸收 bi5，max/max）、X3=bi7[11.6,12.9]
        成顶分型且有缺口（10 < 11.8）；r1=bi3 结束位 11.5，bi4..bi7 期间
        既无反向笔破 11.5、亦无原方向笔破转折点 13 → 候选悬置：
        seg0 收于 bi0..bi2 sure=False，尾段 bi3..bi7 向下 sure=False。
        """
        bars = self._bars([5, 5, 10, 10, 7, 7, 13, 13, 11.5, 11.5,
                           12.8, 12.8, 11.8, 11.8, 12.9, 12.9, 11.6, 11.6])
        bis = [bi(2 * k, 2 * k + 2, "up" if k % 2 == 0 else "down")
               for k in range(8)]
        got = [(s.start_bi, s.end_bi, s.dir.value, s.sure)
               for s in build_fx_segments(bis, bars)]
        assert got == [(0, 2, "up", False), (3, 7, "down", False)]

    def test_gap_pending_cancelled_by_new_extreme(self):
        """古怪线段（课 78/ADR-004）：情况 2 候选被原方向新极值取消 → 原段延续。

        上例候选悬置后，bi8 上破转折点 13（13.2）→ 候选取消、原向上段延续；
        其后特征序列推进到 X4/X5/X6 构成无缺口顶分型（X5=bi11 吸收 bi13，
        高 13.4）→ seg0 终于 bi0..bi10（非 bi0..bi2），尾段 bi11..bi15。
        """
        bars = self._bars([5, 5, 10, 10, 7, 7, 13, 13, 11.5, 11.5,
                           12.8, 12.8, 11.8, 11.8, 12.9, 12.9, 11.6, 11.6,
                           13.2, 13.2, 12.2, 12.2, 13.4, 13.4, 12.4, 12.4,
                           13.1, 13.1, 12.6, 12.6, 13.3, 13.3, 12.3, 12.3])
        bis = [bi(2 * k, 2 * k + 2, "up" if k % 2 == 0 else "down")
               for k in range(16)]
        got = [(s.start_bi, s.end_bi, s.dir.value, s.sure)
               for s in build_fx_segments(bis, bars)]
        assert got == [(0, 10, "up", True), (11, 15, "down", False)]
