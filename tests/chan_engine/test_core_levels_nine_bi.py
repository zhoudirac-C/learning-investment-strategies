"""M7-3 G6：recursion 列九段升级（课 33，claim-20070302-001-b）测试。

口径依据：chanlun-m7-multitimeframe-skill.md §6.4——把中枢延伸 ≥9 笔
（3 子中枢重合门控）→ level+1 的后处理移植进 core/levels.py，
recursion 列 ZS-003 转 PASS；其余校准用例不回退。
"""
from __future__ import annotations

import pytest

from chan_engine.core.levels import detect_nine_bi_zs
from chan_engine.spec.case_io import load_case
from chan_engine.spec.model import Bi, Direction


def _case_bi_bars(case_id):
    """加载校准用例的 expect 笔表（全 sure）与 bars。"""
    case = load_case(f"src/chan_engine/spec/cases/{case_id}.yaml")
    bi_list = [
        Bi(start_idx=b["start_idx"], end_idx=b["end_idx"],
           dir=Direction(b["dir"]), sure=True)
        for b in case.expect["bi"]
    ]
    return bi_list, case.bars


class TestDetectNineBiZs:
    def test_zs003_upgrades_to_level2(self):
        """ZS-003 锚（课 33）：bi1..bi9 九段 → L2 中枢 [16.5,17.0] idx5→41。"""
        bi_list, bars = _case_bi_bars("zs-003")
        out = detect_nine_bi_zs(bi_list, bars)
        assert len(out) == 1
        z = out[0]
        assert (z.zd, z.zg) == pytest.approx((16.5, 17.0), abs=1e-9)
        assert (z.start_idx, z.end_idx, z.level) == (5, 41, 2)

    def test_fewer_than_9_bi_no_upgrade(self):
        """不足 9 笔的连续重叠不升级（ZS-003 截断前 8 笔）。"""
        bi9, bars9 = _case_bi_bars("zs-003")
        assert detect_nine_bi_zs(bi9[:8], bars9) == []

    def test_gate_fails_when_sub_zs_not_overlapping(self):
        """门控：≥9 笔连续重叠，但第 2 子中枢内部不成立 → 不升级。"""
        # 笔包络（low, high）：bi0 引导上；反向（down）笔 bi1..bi9 两两重叠可延伸；
        # 但 bi4/bi6（同向笔）包络 [18,19] 使第 2 组（bi4,5,6）子中枢不成立。
        ranges = {
            0: (14, 18), 1: (15, 17), 2: (15.2, 17), 3: (15.5, 17),
            4: (18, 19), 5: (15.8, 17), 6: (18, 19), 7: (16, 17),
            8: (15.9, 16.9), 9: (16.2, 17),
        }
        bi_list = []
        bar_specs = []
        for i in range(10):
            lo, hi = ranges[i]
            d = Direction.UP if i % 2 == 0 else Direction.DOWN
            bi_list.append(Bi(start_idx=2 * i, end_idx=2 * i + 1, dir=d))
            if d is Direction.UP:   # up: low=start.l, high=end.h
                bar_specs += [(lo, lo + 0.5), (hi - 0.5, hi)]
            else:                    # down: low=end.l, high=start.h
                bar_specs += [(hi - 0.5, hi), (lo, lo + 0.5)]
        from chan_engine.spec.builders import bars_from_ohlc

        bars = bars_from_ohlc([((lo + hi) / 2, hi, lo, (lo + hi) / 2)
                               for lo, hi in bar_specs])
        assert detect_nine_bi_zs(bi_list, bars) == []


class TestEngineNineBiIntegration:
    def test_zs003_recursion_chart_zs_exact(self):
        """引擎集成：zs-003 全跑 → zs 表精确等于升级后 L2（中间产物被吞并）。"""
        from chan_engine.core.engine import RecursionEngine

        case = load_case("src/chan_engine/spec/cases/zs-003.yaml")
        chart = RecursionEngine().run(case.bars)
        assert len(chart.zs) == 1
        z = chart.zs[0]
        assert (z.zd, z.zg) == pytest.approx((16.5, 17.0), abs=1e-9)
        assert (z.start_idx, z.end_idx, z.level) == (5, 41, 2)

    def test_no_upgrade_cases_unchanged(self):
        """未触发九段升级的用例 zs 表不变（抽锚：bc-002 双中枢原样）。"""
        from chan_engine.core.engine import RecursionEngine

        case = load_case("src/chan_engine/spec/cases/bc-002.yaml")
        chart = RecursionEngine().run(case.bars)
        assert [(round(z.zd, 1), round(z.zg, 1), z.level) for z in chart.zs] == [
            (23.9, 26.2, 2), (22.9, 24.4, 1)]
