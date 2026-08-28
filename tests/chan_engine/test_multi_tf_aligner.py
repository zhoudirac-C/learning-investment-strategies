"""M7-2 跨周期对齐层：TFAligner 切片与边界 case 测试（synthetic，不触网、不依赖 chanpy）。

口径依据：docs/design/chanlun-m7-multitimeframe-skill.md §5。
"""
from __future__ import annotations

import pytest

from chan_engine.multi_tf import model, aligner
from chan_engine.spec.model import Bi, Direction, NormalizedChart

DAILY_DATES = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]

#: 60m 合法 bar 标签：10:30 / 11:30 / 14:00 / 15:00（周期结束时刻）
HOUR_LABELS = ["10:30", "11:30", "14:00", "15:00"]


def make_rows(dates, labels=HOUR_LABELS, complete=1):
    """合成分钟行：每天每时段一根，close 递增。"""
    rows = []
    for d in dates:
        for i, hm in enumerate(labels):
            rows.append({"dt": f"{d} {hm}", "open": 1.0, "high": 1.1,
                         "low": 0.9, "close": 1.0 + len(rows) * 0.001,
                         "volume": 100.0, "complete": complete})
    return rows


def make_bi(start, end):
    return Bi(start_idx=start, end_idx=end,
              dir=Direction.UP if end > start else Direction.DOWN)


# 数据覆盖 08-26 ~ 08-28（12 根），daily 覆盖 08-24 ~ 08-28
ROWS = make_rows(["2026-08-26", "2026-08-27", "2026-08-28"])


def make_aligner(rows=ROWS, dates=DAILY_DATES):
    return aligner.TFAligner(daily_dates=dates, sub_rows={"60m": rows})


class TestSessionValidation:
    """时间戳对齐纪律（§5.3）：dt 形态 + A 股时段校验，异常明确报错。"""

    def test_valid_labels_pass(self):
        make_aligner()  # 构造不抛即通过

    def test_bad_format_raises(self):
        with pytest.raises(aligner.AlignmentError):
            make_aligner(rows=[{"dt": "2026-08-26", "complete": 1}])
        with pytest.raises(aligner.AlignmentError):
            make_aligner(rows=[{"dt": "not-a-date", "complete": 1}])

    def test_lunch_break_raises(self):
        with pytest.raises(aligner.AlignmentError):
            make_aligner(rows=[{"dt": "2026-08-26 12:00", "complete": 1}])

    def test_open_boundary_raises(self):
        """9:30 无 bar 结束标签（首根 60m 收 10:30）。"""
        with pytest.raises(aligner.AlignmentError):
            make_aligner(rows=[{"dt": "2026-08-26 09:30", "complete": 1}])

    def test_after_close_raises(self):
        with pytest.raises(aligner.AlignmentError):
            make_aligner(rows=[{"dt": "2026-08-26 15:01", "complete": 1}])

    def test_session_edges_ok(self):
        make_aligner(rows=[{"dt": "2026-08-26 11:30", "complete": 1},
                           {"dt": "2026-08-26 13:00", "complete": 1},
                           {"dt": "2026-08-26 15:00", "complete": 1}])


class TestPartialFiltering:
    def test_incomplete_rows_excluded(self):
        rows = make_rows(["2026-08-26"]) + [
            {"dt": "2026-08-27 10:30", "open": 1.0, "high": 1.1, "low": 0.9,
             "close": 1.05, "volume": 50.0, "complete": 0},
        ]
        a = make_aligner(rows=rows, dates=DAILY_DATES)
        s = a.slice_bi(make_bi(2, 3), "60m")
        # 未完成 bar 被剔除，切片只含 08-26 的 4 根
        assert (s.start_pos, s.end_pos) == (0, 4)

    def test_include_partial_keeps_rows(self):
        """include_partial=True（盘中观察）保留 complete=0 行。"""
        rows = make_rows(["2026-08-26"]) + [
            {"dt": "2026-08-27 10:30", "open": 1.0, "high": 1.1, "low": 0.9,
             "close": 1.05, "volume": 50.0, "complete": 0},
        ]
        a = aligner.TFAligner(DAILY_DATES, {"60m": rows}, include_partial=True)
        s = a.slice_bi(make_bi(2, 3), "60m")
        assert (s.start_pos, s.end_pos) == (0, 5)

    def test_complete_none_treated_as_complete(self):
        """complete 为 None 按已完成处理（与 save_minute 同口径，不抛 TypeError）。"""
        rows = [{"dt": "2026-08-26 10:30", "open": 1.0, "high": 1.1,
                 "low": 0.9, "close": 1.05, "volume": 50.0, "complete": None}]
        a = make_aligner(rows=rows)
        s = a.slice_bi(make_bi(2, 2), "60m")
        assert (s.start_pos, s.end_pos) == (0, 1)


class TestSliceBi:
    def test_basic_slice_positions_and_window(self):
        a = make_aligner()
        s = a.slice_bi(make_bi(2, 3), "60m")  # 08-26 ~ 08-27
        assert s.bi_ref == (2, 3)
        assert s.tf == "60m"
        assert s.window == ("2026-08-26 00:00", "2026-08-27 15:00")
        assert (s.start_pos, s.end_pos) == (0, 8)  # 08-26 4 根 + 08-27 4 根
        assert s.coverage is True
        assert s.note == ""

    def test_empty_slice_coverage_false(self):
        """切片空窗 → coverage=False + 标注'次级别数据不足'（禁止静默降级）。"""
        a = make_aligner()
        s = a.slice_bi(make_bi(0, 1), "60m")  # 08-24 ~ 08-25，分钟数据 08-26 起
        assert s.coverage is False
        assert (s.start_pos, s.end_pos) == (0, 0)
        assert "次级别数据不足" in s.note

    def test_head_missing_coverage_false(self):
        """数据起点晚于窗口起点（前段缺）→ coverage=False。"""
        a = make_aligner()
        s = a.slice_bi(make_bi(1, 2), "60m")  # 窗口 08-25 起，数据 08-26 起
        assert s.coverage is False
        assert "次级别数据不足" in s.note
        assert s.end_pos > s.start_pos  # 有切片但不完整

    def test_tail_missing_coverage_false(self):
        """数据终点早于窗口终点（后段缺）→ coverage=False。"""
        rows = make_rows(["2026-08-26", "2026-08-27"])  # 数据止于 08-27
        a = make_aligner(rows=rows)
        s = a.slice_bi(make_bi(3, 4), "60m")  # 窗口 08-27 ~ 08-28
        assert s.coverage is False
        assert "次级别数据不足" in s.note

    def test_window_entirely_after_data(self):
        """窗口整体晚于数据终点 → 空切片 coverage=False（不得 StopIteration）。"""
        rows = make_rows(["2026-08-26", "2026-08-27"])
        a = make_aligner(rows=rows)
        s = a.slice_bi(make_bi(4, 4), "60m")  # 窗口 08-28 全天，数据止于 08-27
        assert s.coverage is False
        assert (s.start_pos, s.end_pos) == (len(rows), len(rows))
        assert "次级别数据不足" in s.note

    def test_bi_index_out_of_range_raises(self):
        a = make_aligner()
        with pytest.raises(aligner.AlignmentError):
            a.slice_bi(make_bi(7, 9), "60m")

    def test_unknown_tf_raises(self):
        a = make_aligner()
        with pytest.raises(aligner.AlignmentError):
            a.slice_bi(make_bi(2, 3), "15m")

    def test_slice_rows_returns_window_rows(self):
        a = make_aligner()
        s = a.slice_bi(make_bi(2, 3), "60m")
        rows = a.slice_rows(s)
        assert [r["dt"] for r in rows] == [r["dt"] for r in ROWS[:8]]

    def test_slice_sorted_regardless_of_input_order(self):
        a = make_aligner(rows=list(reversed(ROWS)))
        s = a.slice_bi(make_bi(2, 3), "60m")
        rows = a.slice_rows(s)
        assert [r["dt"] for r in rows] == [r["dt"] for r in ROWS[:8]]


class TestSliceAll:
    def test_per_bi_per_tf(self):
        chart = NormalizedChart(bi=[make_bi(2, 3), make_bi(3, 4)])
        a = aligner.TFAligner(daily_dates=DAILY_DATES,
                              sub_rows={"60m": ROWS, "30m": ROWS})
        slices = a.slice_all(chart)
        assert len(slices) == 4  # 2 笔 × 2 tf
        assert {(s.bi_ref, s.tf) for s in slices} == {
            ((2, 3), "60m"), ((2, 3), "30m"), ((3, 4), "60m"), ((3, 4), "30m")}


class TestBuildMultiTfChart:
    def test_container(self):
        chart = NormalizedChart(bi=[make_bi(2, 3), make_bi(3, 4)])
        mtc = aligner.build_multi_tf_chart(
            chart, DAILY_DATES, {"60m": ROWS, "30m": ROWS})
        assert mtc.daily is chart
        assert mtc.sub == {}  # M7-4 引擎分解后填充
        assert len(mtc.slices) == 4
        assert all(isinstance(s, model.BiSlice) for s in mtc.slices)


class TestTfLabelConversion:
    def test_roundtrip(self):
        assert model.tf_label(60) == "60m"
        assert model.tf_label(30) == "30m"
        assert model.tf_minutes("60m") == 60
        assert model.tf_minutes("30m") == 30

    def test_invalid(self):
        with pytest.raises(ValueError):
            model.tf_label(15)
        with pytest.raises(ValueError):
            model.tf_minutes("15m")
