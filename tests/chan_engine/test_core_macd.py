"""M7-3 G7：calc_macd 移植与背驰主口径切换测试。

口径依据：docs/design/chanlun-m7-multitimeframe-skill.md §7.2（v1.3 改判：
MACD 柱面积为主口径，Σ|Δc| 降为校准对照；两口径测试层隔离——
校准门 expect 断言不动，本文件为 MACD 口径的独立测试锚）。
"""
from __future__ import annotations

import pytest

from chan_engine.core import backchi, macd
from chan_engine.core.segments import build_l0_segments
from chan_engine.spec.builders import bars_from
from chan_engine.spec.model import Bar

CLOSES = [10.0, 10.5, 11.0, 10.8, 10.2, 9.9, 10.1, 10.6, 11.2, 11.5]

# 数值锚（2026-08-28 自 skill chan_analysis.py calc_macd 逐位复现）：
# EMA 首值=首根 close 种子；dif=ema12-ema26；dea 首值=首日 dif；hist=(dif-dea)*2
ANCHORS = {
    0: (0.0, 0.0, 0.0),
    1: (0.03988603988603856, 0.007977207977207712, 0.0638176638176617),
    2: (0.11056728435645624, 0.028495223253057422, 0.16414412220679764),
    8: (0.16390790234898134, 0.09424752571189127, 0.13932075327418014),
    9: (0.23840466700750973, 0.12307895397101497, 0.23065142607298952),
}


class TestCalcMacd:
    def test_numeric_anchor(self):
        dif, dea, hist = macd.calc_macd(CLOSES)
        for i, (d, e, h) in ANCHORS.items():
            assert dif[i] == pytest.approx(d, abs=1e-12)
            assert dea[i] == pytest.approx(e, abs=1e-12)
            assert hist[i] == pytest.approx(h, abs=1e-12)

    def test_seed_rule(self):
        """首值=首根 close 种子：dif[0]=dea[0]=hist[0]=0。"""
        dif, dea, hist = macd.calc_macd([7.7, 8.0, 8.2])
        assert (dif[0], dea[0], hist[0]) == (0.0, 0.0, 0.0)

    def test_properties(self):
        """hist=(dif-dea)*2；dif=ema12-ema26；等长输出。"""
        dif, dea, hist = macd.calc_macd(CLOSES)
        assert len(dif) == len(dea) == len(hist) == len(CLOSES)
        for d, e, h in zip(dif, dea, hist):
            assert h == pytest.approx((d - e) * 2, abs=1e-12)

    def test_flat_series_zero(self):
        dif, dea, hist = macd.calc_macd([5.0] * 30)
        assert all(v == pytest.approx(0.0, abs=1e-15) for v in dif + dea + hist)


def _bars(closes):
    from chan_engine.spec.builders import bars_from_closes

    return bars_from_closes(closes)


class TestMacdArea:
    """MACD 柱面积：笔/段区间 |hist| 求和（闭区间端点 bar）。"""

    def test_bi_area_macd(self):
        bars = _bars(CLOSES)
        hist = macd.calc_macd(CLOSES)[2]
        from chan_engine.spec.model import Bi, Direction

        bi = Bi(start_idx=2, end_idx=5, dir=Direction.DOWN)
        expect = sum(abs(hist[i]) for i in range(2, 6))
        assert backchi._bi_area_macd(bi, hist) == pytest.approx(expect, abs=1e-12)

    def test_segment_area_macd_uses_bi_span(self):
        """段面积 = 段首笔起点 bar ~ 末笔终点 bar 的 |hist| 和（笔区间连续）。"""
        from chan_engine.core.model import SegType
        from chan_engine.spec.model import Bi, Direction

        bars = _bars(CLOSES)
        hist = macd.calc_macd(CLOSES)[2]
        bi_list = [
            Bi(start_idx=1, end_idx=3, dir=Direction.UP),
            Bi(start_idx=3, end_idx=5, dir=Direction.DOWN),
            Bi(start_idx=5, end_idx=8, dir=Direction.UP),
        ]
        seg = SegType(start_bi=0, end_bi=2, dir=Direction.UP, high=12.0, low=9.0)
        expect = sum(abs(hist[i]) for i in range(1, 9))
        assert backchi._segment_area_macd(seg, bi_list, hist) == pytest.approx(expect, abs=1e-12)


class TestAreaModeSwitch:
    """detect_backchi_bsp 双口径：默认 MACD（主口径），sigma=Σ|Δc| 校准对照路径保留。"""

    def _run(self, case_id, area_mode=None):
        from chan_engine.core.engine import RecursionEngine
        from chan_engine.spec.case_io import load_case

        case = load_case(f"src/chan_engine/spec/cases/{case_id}.yaml")
        engine = RecursionEngine()
        base = engine._base.run(case.bars)
        import dataclasses

        bi_list = [dataclasses.replace(b, source="recursion") for b in base.bi]
        segs = build_l0_segments(bi_list, case.bars)
        kwargs = {} if area_mode is None else {"area_mode": area_mode}
        return backchi.detect_backchi_bsp(segs, bi_list, case.bars, **kwargs)

    def test_default_is_macd(self):
        """BC-002（设计 §7.2 实证双口径同向背驰）：默认口径=MACD，结论不变。"""
        bsp = self._run("bc-002")
        assert (46, 1, 2) in [(b.idx, b.bstype, b.level) for b in bsp]
        assert (46, 1, 1) in [(b.idx, b.bstype, b.level) for b in bsp]

    def test_sigma_path_preserved(self):
        """area_mode='sigma' 复现校准门原口径（BC-002 几何校准锚不污染）。"""
        bsp = self._run("bc-002", area_mode="sigma")
        assert (46, 1, 2) in [(b.idx, b.bstype, b.level) for b in bsp]
        assert (46, 1, 1) in [(b.idx, b.bstype, b.level) for b in bsp]

    def test_invalid_area_mode(self):
        with pytest.raises(ValueError):
            self._run("bc-002", area_mode="bogus")

    def test_macd_vs_sigma_both_detect(self):
        """双口径同向场景：两口径都出背驰（BC-002 实证锚）。"""
        macd_bsp = self._run("bc-002")
        sigma_bsp = self._run("bc-002", area_mode="sigma")
        key = lambda b: (b.idx, b.bstype, b.dir, b.level)
        assert sorted(map(key, macd_bsp)) == sorted(map(key, sigma_bsp))
