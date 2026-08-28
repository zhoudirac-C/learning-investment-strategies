"""M7-3 G1/G2：走势类型状态机（core/trend.py）测试。

口径依据：chanlun-m7-multitimeframe-skill.md §6.1（课 17/18/20）：
- 盘整 = 完成走势只含 1 个中枢；趋势 = ≥2 个依次同向、互不重叠的中枢；
- 三演化：延伸（同一中枢延续）/ 新生（同向新中枢不重叠）/ 扩张（波动区间重叠）。
"""
from __future__ import annotations

import pytest

from chan_engine.core.trend import TrendState, analyze_trend
from chan_engine.spec.model import Direction, ZhongShu


def zs(zd, zg, start, end, level=2):
    return ZhongShu(zd=zd, zg=zg, start_idx=start, end_idx=end, level=level)


class TestAnalyzeTrend:
    def test_empty_unknown(self):
        st = analyze_trend([])
        assert st.walk_type == "unknown"
        assert st.zs_count == 0
        assert st.last_event == ""
        assert st.direction is None

    def test_single_zs_consolidation_extension(self):
        st = analyze_trend([zs(10, 12, 0, 10)])
        assert st.walk_type == "consolidation"
        assert st.zs_count == 1
        assert st.last_event == "extension"

    # ── 两中枢趋势（synthetic ≥2 例，§6.5） ──

    def test_two_nonoverlap_up_trend(self):
        st = analyze_trend([zs(10, 12, 0, 10), zs(13, 15, 12, 20)])
        assert st.walk_type == "trend"
        assert st.direction is Direction.UP
        assert st.last_event == "new"
        assert st.zs_count == 2

    def test_two_nonoverlap_down_trend(self):
        st = analyze_trend([zs(13, 15, 0, 10), zs(10, 12, 12, 20)])
        assert st.walk_type == "trend"
        assert st.direction is Direction.DOWN
        assert st.last_event == "new"

    def test_three_zs_same_direction_trend(self):
        st = analyze_trend([zs(10, 12, 0, 10), zs(13, 15, 12, 20), zs(16, 18, 22, 30)])
        assert st.walk_type == "trend"
        assert st.direction is Direction.UP
        assert st.zs_count == 3

    def test_boundary_touch_is_nonoverlap(self):
        """严格不重叠口径：next.zd == prev.zg（单点相接）不算重叠 → 趋势成立。"""
        st = analyze_trend([zs(10, 12, 0, 10), zs(12, 14, 12, 20)])
        assert st.walk_type == "trend"
        assert st.direction is Direction.UP

    # ── 中枢扩张（synthetic ≥2 例，§6.5） ──

    def test_overlap_up_expansion(self):
        """上移但区间重叠 → 扩张（级别扩张，仍判盘整）。"""
        st = analyze_trend([zs(10, 12, 0, 10), zs(11, 13, 12, 20)])
        assert st.walk_type == "consolidation"
        assert st.last_event == "expansion"
        assert st.direction is None

    def test_overlap_down_expansion(self):
        st = analyze_trend([zs(11, 13, 0, 10), zs(10, 12, 12, 20)])
        assert st.walk_type == "consolidation"
        assert st.last_event == "expansion"

    def test_trend_then_expansion_endstate_consolidation(self):
        """前两中枢趋势 + 末对重叠 → 整体 consolidation，last_event=expansion。"""
        st = analyze_trend([zs(10, 12, 0, 10), zs(13, 15, 12, 20), zs(14, 16, 22, 30)])
        assert st.walk_type == "consolidation"
        assert st.last_event == "expansion"

    def test_mixed_direction_not_single_trend(self):
        """一上一下不重叠 → 非单一趋势（依次同向被破坏）。"""
        st = analyze_trend([zs(10, 12, 0, 10), zs(14, 16, 12, 20), zs(10.5, 12.5, 22, 30)])
        assert st.walk_type == "consolidation"
        assert st.last_event == "new"  # 末对不重叠 → 新生（但方向切换）
        assert st.direction is None

    def test_zs_list_carried(self):
        zlist = [zs(13, 15, 12, 20), zs(10, 12, 0, 10)]  # 乱序输入
        st = analyze_trend(zlist)
        # 输出按时间排序（拷贝，不改调用方列表）
        assert [(z.start_idx) for z in st.zs_list] == [0, 12]
        assert [z.start_idx for z in zlist] == [12, 0]


class TestEngineWiring:
    """engine 挂接：NormalizedChart.trend = 最高 level 同级别中枢的 analyze_trend。"""

    def test_chart_carries_trend_state(self):
        from chan_engine.core.engine import RecursionEngine
        from chan_engine.spec.case_io import load_case

        case = load_case("src/chan_engine/spec/cases/bc-002.yaml")
        chart = RecursionEngine().run(case.bars)
        assert chart.trend is not None
        # BC-002 仅 1 个 L2 中枢 → 盘整（延伸）
        assert chart.trend.walk_type == "consolidation"
        assert chart.trend.last_event == "extension"

    def test_zs003_upgraded_single_l2(self):
        """ZS-003（G6 升级后）：单 L2 中枢 → consolidation。"""
        from chan_engine.core.engine import RecursionEngine
        from chan_engine.spec.case_io import load_case

        case = load_case("src/chan_engine/spec/cases/zs-003.yaml")
        chart = RecursionEngine().run(case.bars)
        assert chart.trend is not None
        assert chart.trend.walk_type == "consolidation"
