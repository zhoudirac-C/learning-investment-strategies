"""Task 3: synthetic 构造助手测试。

两种输入：①收盘价序列字符串 "10,11,9,12,8"（自动配默认振幅生成合法 o/h/l/c）；
②显式 (o,h,l,c) 元组列表。自动补 ts（递增）与 vol（常量）。
合法性保证：h>=max(o,c)、l<=min(o,c)。
"""

import textwrap

import pytest

from chan_engine.spec.builders import (
    DEFAULT_AMPLITUDE,
    bars_from,
    bars_from_closes,
    bars_from_ohlc,
)
from chan_engine.spec.case_io import load_case
from chan_engine.spec.model import Bar

CLOSES = "10,11,9,12,8"


def assert_legal(bar: Bar) -> None:
    assert bar.h >= max(bar.o, bar.c)
    assert bar.l <= min(bar.o, bar.c)


class TestBarsFromCloses:
    def test_close_string(self):
        bars = bars_from_closes(CLOSES)
        assert len(bars) == 5
        assert [b.c for b in bars] == [10, 11, 9, 12, 8]
        assert [b.ts for b in bars] == [0, 1, 2, 3, 4]
        assert len({b.vol for b in bars}) == 1  # vol 常量
        for b in bars:
            assert_legal(b)

    def test_whitespace_and_floats_tolerated(self):
        bars = bars_from_closes(" 10 , 11.5 ,9 ")
        assert [b.c for b in bars] == [10, 11.5, 9]

    def test_close_sequence_list_also_accepted(self):
        bars = bars_from_closes([10, 11, 9])
        assert [b.c for b in bars] == [10, 11, 9]

    def test_open_defaults_to_previous_close(self):
        bars = bars_from_closes(CLOSES)
        assert bars[0].o == 10  # 首根无前收，o=c
        assert bars[1].o == 10
        assert bars[2].o == 11

    def test_default_amplitude(self):
        bars = bars_from_closes("10,11")
        assert bars[0].h == 10 + DEFAULT_AMPLITUDE
        assert bars[0].l == 10 - DEFAULT_AMPLITUDE

    def test_custom_amplitude_and_vol_and_ts0(self):
        bars = bars_from_closes("10,12", amplitude=1.0, vol=5.0, ts0=100)
        assert bars[0].h == 11 and bars[0].l == 9  # o=c=10, ±1.0
        assert bars[1].h == 13 and bars[1].l == 9  # o=10, c=12, ±1.0
        assert bars[0].ts == 100 and bars[1].ts == 101
        assert all(b.vol == 5.0 for b in bars)

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            bars_from_closes("")

    def test_non_positive_amplitude_raises(self):
        with pytest.raises(ValueError):
            bars_from_closes("10,11", amplitude=0)


class TestBarsFromOhlc:
    ROWS = [(10, 11, 9, 10.5), (10.5, 12, 10, 11.5), (11.5, 12, 8, 9)]

    def test_explicit_tuples(self):
        bars = bars_from_ohlc(self.ROWS)
        assert [(b.o, b.h, b.l, b.c) for b in bars] == [
            (10, 11, 9, 10.5),
            (10.5, 12, 10, 11.5),
            (11.5, 12, 8, 9),
        ]
        assert [b.ts for b in bars] == [0, 1, 2]
        assert len({b.vol for b in bars}) == 1
        for b in bars:
            assert_legal(b)

    def test_doji_bar_legal(self):
        bars = bars_from_ohlc([(10, 10, 10, 10)])
        assert_legal(bars[0])

    @pytest.mark.parametrize(
        "row",
        [
            (10, 10.4, 9, 10.5),  # h < c
            (10, 10.9, 9, 11),  # h < c(11)
            (10, 11, 10.2, 10.5),  # l > o
        ],
    )
    def test_illegal_row_raises(self, row):
        with pytest.raises(ValueError, match="h>=max"):
            bars_from_ohlc([row])

    def test_bad_row_shape_raises(self):
        with pytest.raises(ValueError):
            bars_from_ohlc([(10, 11, 9)])

    def test_empty_rows_raise(self):
        with pytest.raises(ValueError):
            bars_from_ohlc([])


class TestBarsFromDispatcher:
    def test_string_goes_to_closes(self):
        bars = bars_from(CLOSES)
        assert [b.c for b in bars] == [10, 11, 9, 12, 8]

    def test_rows_go_to_ohlc(self):
        bars = bars_from([[10, 11, 9, 10.5], [10.5, 12, 10, 11.5]])
        assert [(b.o, b.h, b.l, b.c) for b in bars] == [
            (10, 11, 9, 10.5),
            (10.5, 12, 10, 11.5),
        ]


class TestCaseIoStringBars:
    """case_io 接受紧凑记法 bars（委托 builders）。"""

    def test_load_case_with_close_string_bars(self, tmp_path):
        p = tmp_path / "case.yaml"
        p.write_text(
            textwrap.dedent(
                """\
                case_id: FX-TEST-001
                claim_refs: [claim-20070905-001-b]
                bars: "10,11,9,12,8"
                expect: {}
                """
            ),
            encoding="utf-8",
        )
        case = load_case(p)
        assert [b.c for b in case.bars] == [10, 11, 9, 12, 8]
        assert [b.ts for b in case.bars] == [0, 1, 2, 3, 4]
        for b in case.bars:
            assert_legal(b)
