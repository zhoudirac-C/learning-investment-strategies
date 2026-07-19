"""Task 6: diff 引擎测试（先红后绿）。

比对语义（实施计划 Task 6 Step 1/2）：
- 全一致 → PASS；
- 一笔端点差 1 → FAIL，且 diff 定位到 bi 表、给出缺/多元素（主键含端点）；
- 主键命中后字段不一致（如 sure）→ FAIL，diff 指明字段与期望/实际值；
- actual.na_fields 标记的表整体跳过；expect 中不出现的表跳过（用例不断言）；
- float 字段（zs 的 zd/zg）容差参数生效，默认 0 严格。
"""

import pytest

from chan_engine.harness.diff import (
    ChartDiff,
    TableDiff,
    diff_charts,
    diff_expect,
    expect_to_chart,
)
from chan_engine.spec.model import (
    Bi,
    BSPoint,
    Direction,
    FX,
    NormalizedChart,
    Segment,
    ZhongShu,
)

# 覆盖五张表的 expect（dir 用 YAML 里的字符串写法）
FULL_EXPECT = {
    "fx": [
        {"idx": 1, "type": "up"},
        {"idx": 4, "type": "down", "sure": False},
    ],
    "bi": [{"start_idx": 1, "end_idx": 4, "dir": "down", "sure": False}],
    "seg": [{"start_bi": 0, "end_bi": 2, "dir": "up"}],
    "zs": [{"zd": 10.0, "zg": 12.0, "start_idx": 1, "end_idx": 6, "level": 1}],
    "bsp": [{"idx": 4, "bstype": 1, "dir": "down"}],
}


def chart_matching_full() -> NormalizedChart:
    """与 FULL_EXPECT 逐字段一致的归一输出。"""
    return NormalizedChart(
        fx=[FX(1, Direction.UP), FX(4, Direction.DOWN, sure=False)],
        bi=[Bi(1, 4, Direction.DOWN, sure=False)],
        seg=[Segment(0, 2, Direction.UP)],
        zs=[ZhongShu(zd=10.0, zg=12.0, start_idx=1, end_idx=6, level=1)],
        bsp=[BSPoint(4, 1, Direction.DOWN)],
    )


class TestExpectToChart:
    """expect 原始 dict → NormalizedChart 归一。"""

    def test_direction_strings_and_defaults(self):
        chart = expect_to_chart(FULL_EXPECT)
        assert chart.fx[0] == FX(1, Direction.UP)  # sure 默认 True
        assert chart.bi[0].dir is Direction.DOWN
        assert chart.bi[0].sure is False
        assert chart.seg[0].start_bi == 0
        assert chart.zs[0].level == 1
        assert chart.bsp[0].bstype == 1

    def test_absent_tables_stay_empty(self):
        chart = expect_to_chart({"bi": [{"start_idx": 0, "end_idx": 2, "dir": "down"}]})
        assert chart.fx == [] and chart.seg == [] and chart.zs == [] and chart.bsp == []

    def test_unknown_table_raises(self):
        with pytest.raises(ValueError, match="macd"):
            expect_to_chart({"macd": []})

    def test_unknown_entry_field_raises(self):
        with pytest.raises(ValueError, match="end_id"):
            expect_to_chart({"bi": [{"start_idx": 0, "end_id": 2, "dir": "down"}]})

    def test_non_list_table_raises(self):
        with pytest.raises(ValueError, match="bi"):
            expect_to_chart({"bi": {"start_idx": 0}})

    def test_bad_direction_raises(self):
        with pytest.raises(ValueError, match="upx"):
            expect_to_chart({"bi": [{"start_idx": 0, "end_idx": 2, "dir": "upx"}]})


class TestDiffPass:
    def test_full_consistent_passes(self):
        d = diff_expect(FULL_EXPECT, chart_matching_full())
        assert isinstance(d, ChartDiff)
        assert d.passed is True
        assert d.problem_tables == []
        assert all(t.status == "ok" for t in d.tables)

    def test_empty_expect_passes_anything(self):
        # expect {} = 用例不做任何断言（五表全 no-expect 跳过）
        d = diff_expect({}, chart_matching_full())
        assert d.passed is True
        assert all(t.status == "skipped" and t.skip_reason == "no-expect" for t in d.tables)


class TestDiffFail:
    def test_bi_endpoint_off_by_one(self):
        """一笔端点差 1 → FAIL；主键对齐下表现为缺 (0,5,up) / 多 (0,6,up)。"""
        d = diff_expect(
            {"bi": [{"start_idx": 0, "end_idx": 5, "dir": "up"}]},
            NormalizedChart(bi=[Bi(0, 6, Direction.UP)]),
        )
        assert d.passed is False
        (bi,) = d.problem_tables
        assert bi.table == "bi"
        assert bi.mismatches == []
        assert [type(e) for e in bi.missing] == [Bi]
        assert [(e.start_idx, e.end_idx, e.dir) for e in bi.missing] == [
            (0, 5, Direction.UP)
        ]
        assert [(e.start_idx, e.end_idx, e.dir) for e in bi.extra] == [
            (0, 6, Direction.UP)
        ]

    def test_sure_field_mismatch_points_to_field(self):
        d = diff_expect(
            {"bi": [{"start_idx": 0, "end_idx": 5, "dir": "up", "sure": True}]},
            NormalizedChart(bi=[Bi(0, 5, Direction.UP, sure=False)]),
        )
        assert d.passed is False
        (bi,) = d.problem_tables
        assert bi.missing == [] and bi.extra == []
        (m,) = bi.mismatches
        assert m.table == "bi"
        assert m.key == (0, 5, "up")  # 主键机读化（Direction → value）
        assert m.field == "sure"
        assert m.expected is True and m.actual is False

    def test_fx_alignment_uses_idx_and_type(self):
        # 同 idx 不同类型 = 不同分型 → 缺/多，而不是字段不一致
        d = diff_expect(
            {"fx": [{"idx": 3, "type": "up"}]},
            NormalizedChart(fx=[FX(3, Direction.DOWN)]),
        )
        (fx,) = d.problem_tables
        assert len(fx.missing) == 1 and len(fx.extra) == 1 and fx.mismatches == []

    def test_zs_aligned_by_span_compares_zd_zg(self):
        d = diff_expect(
            {"zs": [{"zd": 10.0, "zg": 12.0, "start_idx": 1, "end_idx": 6}]},
            NormalizedChart(zs=[ZhongShu(zd=10.5, zg=12.0, start_idx=1, end_idx=6)]),
        )
        (zs,) = d.problem_tables
        assert [(m.field, m.expected, m.actual) for m in zs.mismatches] == [
            ("zd", 10.0, 10.5)
        ]


class TestSkipRules:
    def test_na_fields_tables_skipped(self):
        """na_fields 标记的表即使 expect 有断言也整体跳过（czsc 的 seg/bsp）。"""
        chart = chart_matching_full()
        chart.seg = []  # czsc 不产出
        chart.bsp = []
        chart.na_fields = {"seg", "bsp"}
        d = diff_expect(FULL_EXPECT, chart)
        by_table = {t.table: t for t in d.tables}
        assert by_table["seg"].status == "skipped"
        assert by_table["seg"].skip_reason == "na"
        assert by_table["bsp"].status == "skipped"
        assert d.passed is True  # 其余表一致

    def test_absent_expect_table_skipped(self):
        """expect 只断言 bi：actual 多出的 fx 不导致 FAIL。"""
        d = diff_expect(
            {"bi": [{"start_idx": 0, "end_idx": 2, "dir": "down"}]},
            NormalizedChart(
                bi=[Bi(0, 2, Direction.DOWN)],
                fx=[FX(0, Direction.DOWN), FX(2, Direction.UP), FX(9, Direction.UP)],
            ),
        )
        assert d.passed is True
        by_table = {t.table: t for t in d.tables}
        assert by_table["fx"].skip_reason == "no-expect"
        assert by_table["bi"].status == "ok"


class TestTolerance:
    ZS_EXPECT = {"zs": [{"zd": 10.0, "zg": 12.0, "start_idx": 1, "end_idx": 6}]}

    def _chart(self, zd):
        return NormalizedChart(zs=[ZhongShu(zd=zd, zg=12.0, start_idx=1, end_idx=6)])

    def test_strict_by_default(self):
        assert diff_expect(self.ZS_EXPECT, self._chart(10.01)).passed is False

    def test_within_tolerance_passes(self):
        d = diff_expect(self.ZS_EXPECT, self._chart(10.01), tolerance=0.01)
        assert d.passed is True

    def test_tolerance_does_not_apply_to_non_float_fields(self):
        # sure/索引等字段永远严格，容差不生效
        d = diff_expect(
            {"bi": [{"start_idx": 0, "end_idx": 5, "dir": "up", "sure": True}]},
            NormalizedChart(bi=[Bi(0, 5, Direction.UP, sure=False)]),
            tolerance=100.0,
        )
        assert d.passed is False

    def test_diff_charts_rejects_unknown_table(self):
        with pytest.raises(ValueError, match="macd"):
            diff_charts(NormalizedChart(), NormalizedChart(), tables={"macd"})
