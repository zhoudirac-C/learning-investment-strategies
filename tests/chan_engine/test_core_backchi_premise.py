"""M7-3 G3：背驰前提校验（"没有趋势没有背驰" L15/L24）测试。

口径依据：chanlun-m7-multitimeframe-skill.md §6.2：
三件套所在走势含 ≥2 同向不重叠中枢 → trend_div（标准一买/一卖）；
仅 1 中枢 → consolidation_div（盘整背驰，防误报为反转信号）。
"""
from __future__ import annotations

import pytest

from chan_engine.core import backchi
from chan_engine.spec.model import Direction, ZhongShu


def zs(zd, zg, start, end, level=2):
    return ZhongShu(zd=zd, zg=zg, start_idx=start, end_idx=end, level=level)


class TestClassifyBackchiType:
    """纯函数：当前中枢 + 历史同级别中枢 + 走势方向 → 背驰类型。"""

    # ── 盘整背驰（≥2 例） ──

    def test_no_prior_zs_consolidation(self):
        cur = zs(10, 12, 20, 30)
        assert backchi.classify_backchi_type([cur], cur, Direction.DOWN) == "consolidation_div"

    def test_prior_overlapping_zs_consolidation(self):
        """前中枢与当前重叠（扩张）→ 非趋势 → 盘整背驰。"""
        prior = zs(11, 13, 0, 18)
        cur = zs(10, 12, 20, 30)
        assert backchi.classify_backchi_type([prior, cur], cur, Direction.DOWN) == "consolidation_div"

    # ── 趋势背驰（≥2 例） ──

    def test_prior_nonoverlap_down_trend(self):
        """下跌趋势：前中枢整体在当前上方（prior.zd > cur.zg）→ 趋势背驰。"""
        prior = zs(14, 16, 0, 18)
        cur = zs(10, 12, 20, 30)
        assert backchi.classify_backchi_type([prior, cur], cur, Direction.DOWN) == "trend_div"

    def test_prior_nonoverlap_up_trend(self):
        """上涨趋势：前中枢整体在当前下方（prior.zg < cur.zd）→ 趋势背驰。"""
        prior = zs(8, 9, 0, 18)
        cur = zs(10, 12, 20, 30)
        assert backchi.classify_backchi_type([prior, cur], cur, Direction.UP) == "trend_div"

    def test_wrong_direction_prior_ignored(self):
        """前中枢不重叠但方向相反（下跌走势中前中枢在下方）→ 不算同向 → 盘整背驰。"""
        prior = zs(7, 8, 0, 18)
        cur = zs(10, 12, 20, 30)
        assert backchi.classify_backchi_type([prior, cur], cur, Direction.DOWN) == "consolidation_div"

    def test_only_same_level_counted(self):
        """级别过滤：L1 前中枢不参与 L2 走势的趋势判定。"""
        prior_l1 = zs(14, 16, 0, 18, level=1)
        cur = zs(10, 12, 20, 30, level=2)
        assert backchi.classify_backchi_type([prior_l1, cur], cur, Direction.DOWN) == "consolidation_div"

    def test_prior_must_precede(self):
        """时间序：当前之后的中枢不参与前提判定。"""
        later = zs(14, 16, 40, 50)
        cur = zs(10, 12, 20, 30)
        assert backchi.classify_backchi_type([cur, later], cur, Direction.DOWN) == "consolidation_div"


class TestDetectBackchiBspAnnotation:
    """detect_backchi_bsp 集成：bstype=1 输出带 backchi_type 标注。"""

    def _bc002(self, zs_list=None):
        import dataclasses

        from chan_engine.core.engine import RecursionEngine
        from chan_engine.core.segments import build_l0_segments
        from chan_engine.spec.case_io import load_case

        case = load_case("src/chan_engine/spec/cases/bc-002.yaml")
        engine = RecursionEngine()
        base = engine._base.run(case.bars)
        bi_list = [dataclasses.replace(b, source="recursion") for b in base.bi]
        segs = build_l0_segments(bi_list, case.bars)
        kwargs = {} if zs_list is None else {"zs_list": zs_list}
        return backchi.detect_backchi_bsp(segs, bi_list, case.bars, **kwargs)

    def test_legacy_call_no_zs_list_leaves_empty(self):
        """不传 zs_list（既有直调）→ backchi_type 留空（向后兼容）。"""
        bsp = self._bc002()
        assert bsp and all(b.backchi_type == "" for b in bsp)

    def test_bc002_consolidation_div(self):
        """BC-002 单 L2 中枢 → 盘整背驰标注（bsp 位置/数量不变）。"""
        from chan_engine.core.engine import RecursionEngine
        from chan_engine.spec.case_io import load_case

        case = load_case("src/chan_engine/spec/cases/bc-002.yaml")
        chart = RecursionEngine().run(case.bars)
        ones = [b for b in chart.bsp if b.bstype == 1]
        assert len(ones) == 2  # L1+L2 @46 不变
        assert all(b.backchi_type == "consolidation_div" for b in ones)
