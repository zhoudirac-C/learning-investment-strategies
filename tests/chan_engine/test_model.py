"""Task 1: 归一数据模型测试。

字段口径以 docs/superpowers/plans/2026-07-18-chanlun-quant-m1-calibration-gate.md
Task 1 为准：Bar=(ts,o,h,l,c,vol)；FX=(idx,type,sure)；Bi=(start_idx,end_idx,dir,sure)；
Segment=(start_bi,end_bi,dir,sure)；ZhongShu=(zd,zg,start_idx,end_idx,level,sure)；
BSPoint=(idx,bstype(1/2/3),dir,level,sure)。每个结构元素带 sure(默认 True) 与 source(默认 "")。
"""

import pytest

from chan_engine.spec.model import (
    FX,
    Bar,
    Bi,
    BSPoint,
    Direction,
    NormalizedChart,
    Segment,
    ZhongShu,
)


class TestDirection:
    def test_has_up_and_down(self):
        assert Direction.UP is not Direction.DOWN
        assert {Direction.UP, Direction.DOWN} == set(Direction)


class TestBar:
    def test_fields(self):
        bar = Bar(ts=0, o=10.0, h=11.0, l=9.0, c=10.5, vol=1000.0)
        assert (bar.ts, bar.o, bar.h, bar.l, bar.c, bar.vol) == (
            0,
            10.0,
            11.0,
            9.0,
            10.5,
            1000.0,
        )


class TestStructuralElements:
    """每个结构元素：位置/方向字段 + sure(默认 True) + source(默认 "")。"""

    def test_fx_defaults(self):
        fx = FX(idx=3, type=Direction.UP)
        assert fx.idx == 3
        assert fx.type is Direction.UP
        assert fx.sure is True
        assert fx.source == ""

    def test_bi_defaults(self):
        bi = Bi(start_idx=0, end_idx=5, dir=Direction.DOWN)
        assert (bi.start_idx, bi.end_idx, bi.dir) == (0, 5, Direction.DOWN)
        assert bi.sure is True
        assert bi.source == ""

    def test_segment_defaults(self):
        seg = Segment(start_bi=0, end_bi=2, dir=Direction.UP)
        assert (seg.start_bi, seg.end_bi, seg.dir) == (0, 2, Direction.UP)
        assert seg.sure is True
        assert seg.source == ""

    def test_zhongshu_defaults(self):
        zs = ZhongShu(zd=10.0, zg=12.0, start_idx=1, end_idx=8)
        assert (zs.zd, zs.zg, zs.start_idx, zs.end_idx) == (10.0, 12.0, 1, 8)
        assert zs.level == 1
        assert zs.sure is True
        assert zs.source == ""

    def test_bspoint_defaults(self):
        bsp = BSPoint(idx=7, bstype=1, dir=Direction.UP)
        assert (bsp.idx, bsp.bstype, bsp.dir) == (7, 1, Direction.UP)
        assert bsp.level == 1
        assert bsp.sure is True
        assert bsp.source == ""

    def test_sure_and_source_overridable(self):
        fx = FX(idx=1, type=Direction.DOWN, sure=False, source="chanpy")
        assert fx.sure is False
        assert fx.source == "chanpy"

    @pytest.mark.parametrize("bstype", [1, 2, 3])
    def test_bspoint_valid_bstype(self, bstype):
        assert BSPoint(idx=0, bstype=bstype, dir=Direction.UP).bstype == bstype

    @pytest.mark.parametrize("bstype", [0, 4, -1])
    def test_bspoint_invalid_bstype_raises(self, bstype):
        with pytest.raises(ValueError):
            BSPoint(idx=0, bstype=bstype, dir=Direction.UP)


class TestNormalizedChart:
    def test_five_tables_default_empty(self):
        chart = NormalizedChart()
        assert chart.fx == []
        assert chart.bi == []
        assert chart.seg == []
        assert chart.zs == []
        assert chart.bsp == []

    def test_na_fields_default_empty(self):
        chart = NormalizedChart()
        assert not chart.na_fields
        chart.na_fields.add("seg")
        assert "seg" in chart.na_fields

    def test_tables_not_shared_between_instances(self):
        a = NormalizedChart()
        b = NormalizedChart()
        a.bi.append(Bi(start_idx=0, end_idx=1, dir=Direction.UP))
        a.na_fields.add("bsp")
        assert b.bi == []
        assert not b.na_fields

    def test_tables_hold_elements(self):
        chart = NormalizedChart(
            fx=[FX(idx=2, type=Direction.UP)],
            zs=[ZhongShu(zd=1.0, zg=2.0, start_idx=0, end_idx=3)],
        )
        assert chart.fx[0].idx == 2
        assert chart.zs[0].zg == 2.0
