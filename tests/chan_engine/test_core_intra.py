"""M7-7 T1: core/intra.py 段内笔级重释测试。

口径（B-2 影子 `scripts/chan_b2_shadow.py` 为可执行规范，ADR-012 B 演进）：
- fx 段（课 67 特征序列线段）不拆，段内按"同向笔创/未创段方向新极值"分
  推动笔/修正笔，修正笔 run 夹出中枢 span（课 17 首三笔严格重叠 + 已确认笔延伸）；
- 单中枢 + 进入腿 ≥3 笔 → 盘整：中枢 L2 + 离开腿内 L1 + 双级别背驰（MACD 主口径）；
- 单中枢 + 进入腿 <3 笔 / 修正结构未确认 → Path B：段首三笔 → L1；
- ≥2 中枢 → 趋势：各 L1 + 趋势背驰（连接腿 vs 末离开腿）。

锚定用例：
- BC-002：fx 九并一段内重构 进入 bi0-2 / 中枢 [23.9,26.2]@16→31 / 离开
  [22.9,24.4]@31→46 + 双级别一买@46（盘整背驰标注）；
- BSP-003：Path B 段首三笔 [11.4,14.0]@1→16（尾部悬置修正结构）；
- BC-001：趋势双中枢 [26.3,29.3]@6→21 + [22.7,24.8]@26→41（各 L1）；
- ZS-001：纯推动段（同向笔连创新极值）→ 空产出；
- sure 透传：离开腿含未确认笔 → 买卖点 sure=False。
"""

from __future__ import annotations

import pytest

from chan_engine.core.intra import decompose_segment, emit_intra_zs_bsp
from chan_engine.core.macd import calc_macd
from chan_engine.core.segments_fx import build_fx_segments
from chan_engine.harness.adapter_chanpy import ChanPyAdapter
from chan_engine.spec.case_io import load_case

CASES_DIR = "src/chan_engine/spec/cases"


def _seg_and_ctx(case_name: str, seg_idx: int = 0):
    case = load_case(f"{CASES_DIR}/{case_name}.yaml")
    bi = ChanPyAdapter().run(case.bars).bi
    segs = build_fx_segments(bi, case.bars)
    hist = calc_macd([float(b.c) for b in case.bars])[2]
    return segs[seg_idx], bi, case.bars, hist


class TestDecompose:
    def test_bc002_split(self):
        """BC-002：fx 九并一段 → 进入 bi0-2 / 中枢 span bi3-5 / 离开 bi6-8。"""
        seg, bi, bars, _ = _seg_and_ctx("bc-002")
        pos, spans, legs, had_corrective = decompose_segment(seg, bi, bars)
        assert spans == [[3, 4, 5]]
        assert legs == [[0, 1, 2], [6, 7, 8]]
        assert had_corrective

    def test_bc001_two_consolidations(self):
        """BC-001：两个修正 run → 两个中枢 span（bi1-3、bi5-7）。"""
        seg, bi, bars, _ = _seg_and_ctx("bc-001")
        pos, spans, legs, _ = decompose_segment(seg, bi, bars)
        assert spans == [[1, 2, 3], [5, 6, 7]]
        assert legs == [[0], [4], [8]]

    def test_bsp003_tail_suspension(self):
        """BSP-003：修正 run 缺后续反向笔确认（bi5 unsure 剔除）→ 无 span 但曾修正。"""
        seg, bi, bars, _ = _seg_and_ctx("bsp-003")
        pos, spans, legs, had_corrective = decompose_segment(seg, bi, bars)
        assert spans == []
        assert had_corrective

    def test_zs001_pure_impulse(self):
        """ZS-001：同向笔连创新极值（纯推动）→ 无修正、无 span。"""
        seg, bi, bars, _ = _seg_and_ctx("zs-001")
        pos, spans, legs, had_corrective = decompose_segment(seg, bi, bars)
        assert spans == []
        assert not had_corrective


class TestEmit:
    def test_bc002_consolidation_full_structure(self):
        """BC-002 盘整：L2 中枢 + L1 离开腿内中枢 + 双级别一买@46（consolidation_div）。"""
        seg, bi, bars, hist = _seg_and_ctx("bc-002")
        zs, bsp = emit_intra_zs_bsp(seg, bi, bars, hist, zs_context=[])
        assert [(z.zd, z.zg, z.start_idx, z.end_idx, z.level) for z in zs] == [
            (23.9, 26.2, 16, 31, 2),
            (22.9, 24.4, 31, 46, 1),
        ]
        assert [(b.idx, b.bstype, b.dir.value, b.level) for b in bsp] == [
            (46, 1, "up", 2),
            (46, 1, "up", 1),
        ]
        assert all(b.sure for b in bsp)
        assert {b.backchi_type for b in bsp} == {"consolidation_div"}

    def test_bsp003_path_b_seed(self):
        """BSP-003 Path B：段首三笔 [11.4,14.0]@1→16 L1，不直接出买卖点。"""
        seg, bi, bars, hist = _seg_and_ctx("bsp-003")
        zs, bsp = emit_intra_zs_bsp(seg, bi, bars, hist, zs_context=[])
        assert [(z.zd, z.zg, z.start_idx, z.end_idx, z.level) for z in zs] == [
            (11.4, 14.0, 1, 16, 1)
        ]
        assert bsp == []

    def test_bc001_trend_two_l1_zs(self):
        """BC-001 趋势：两个 L1 中枢（笔中枢哲学锚区间恰好命中）。"""
        seg, bi, bars, hist = _seg_and_ctx("bc-001")
        zs, bsp = emit_intra_zs_bsp(seg, bi, bars, hist, zs_context=[])
        assert [(z.zd, z.zg, z.start_idx, z.end_idx, z.level) for z in zs] == [
            (26.3, 29.3, 6, 21, 1),
            (22.7, 24.8, 26, 41, 1),
        ]

    def test_zs001_no_output(self):
        """纯推动段 → 无中枢无买卖点。"""
        seg, bi, bars, hist = _seg_and_ctx("zs-001")
        zs, bsp = emit_intra_zs_bsp(seg, bi, bars, hist, zs_context=[])
        assert zs == [] and bsp == []

    def test_seg004_path_b_on_suspension(self):
        """SEG-004：修正笔无反向确认（尾部悬置）→ Path B 段首三笔。"""
        seg, bi, bars, hist = _seg_and_ctx("seg-004")
        zs, bsp = emit_intra_zs_bsp(seg, bi, bars, hist, zs_context=[])
        assert len(zs) == 1 and zs[0].level == 1
        assert (zs[0].zd, zs[0].zg, zs[0].start_idx) == (12.0, 15.0, 1)
