"""M3-4: 递归层引擎集成测试（6 降级用例端到端 diff 门）。

RecursionEngine：bars → chanpy fx/bi 委托 → L0 段 → 多级 zs/bsp。
断言方式：直接复用校准门 ``diff_expect``——整条用例 PASS 才算过，
逐表（fx/bi/seg/zs/bsp）与 expect 严格对齐。

锚定用例：
- BC-002：level-2 zs + level-1 zs + 双级别一买（M2 双实现 FAIL → 递归层修复）；
- BSP-003：level-1 zs(11.4,14.0,1→16) + 三买@26（同上）；
- BC-001/SEG-001：不产生多余 zs/bsp（不误报的负向锚）。
"""

from __future__ import annotations

import pytest

from chan_engine.core.engine import RecursionEngine
from chan_engine.harness.diff import ChartDiff, diff_expect
from chan_engine.spec.case_io import load_case

CASES_DIR = "src/chan_engine/spec/cases"
GOLDEN_DIR = "src/chan_engine/spec/golden"


def _fmt_diff(d: ChartDiff) -> str:
    parts = []
    for t in d.problem_tables:
        parts.append(
            f"{t.table}: missing={len(t.missing)} extra={len(t.extra)} "
            f"mismatch={[(m.field, m.expected, m.actual) for m in t.mismatches]}"
        )
    return "; ".join(parts)


@pytest.fixture(scope="module")
def engine():
    return RecursionEngine()


def test_bc002_full_chart_passes_gate(engine):
    """BC-002 端到端：fx/bi 委托对齐 + level-2/level-1 双 zs + 双一买。"""
    case = load_case(f"{CASES_DIR}/bc-002.yaml")
    chart = engine.run(case.bars)
    d = diff_expect(case.expect, chart)
    assert d.passed, _fmt_diff(d)


def test_bsp003_full_chart_passes_gate(engine):
    """BSP-003 端到端：level-1 zs + 三买@26（离开+回试不破 ZG）。"""
    case = load_case(f"{CASES_DIR}/bsp-003.yaml")
    chart = engine.run(case.bars)
    d = diff_expect(case.expect, chart)
    assert d.passed, _fmt_diff(d)


def test_bc002_zs_exactly_two(engine):
    """BC-002 zs 表恰好两条（level-2 中枢段 + level-1 离开段），不多发。"""
    case = load_case(f"{CASES_DIR}/bc-002.yaml")
    chart = engine.run(case.bars)
    assert len(chart.zs) == 2
    assert sorted(z.level for z in chart.zs) == [1, 2]


def test_bc002_bsp_order_level_desc(engine):
    """同 idx 双一买按 level 降序（大级别先报，对齐 expect 组内配对顺序）。"""
    case = load_case(f"{CASES_DIR}/bc-002.yaml")
    chart = engine.run(case.bars)
    assert [(b.idx, b.bstype, b.level) for b in chart.bsp] == [(46, 1, 2), (46, 1, 1)]


def test_seg001_no_spurious_bsp(engine):
    """SEG-001 仅 2 段无三件套：不出背驰买卖点（负向锚，防误报）。"""
    case = load_case(f"{CASES_DIR}/seg-001.yaml")
    chart = engine.run(case.bars)
    assert chart.bsp == []


def test_gold001_box_third_buy_passes_gate(engine):
    """GOLD-001（工行日线）：箱体三买代理产出唯一 bsp3@34（课文 12-14）。"""
    case = load_case(f"{GOLDEN_DIR}/gold-001.yaml")
    chart = engine.run(case.bars)
    assert [(b.idx, b.bstype, b.dir.value, b.level) for b in chart.bsp] == [
        (34, 3, "up", 1)
    ]
    d = diff_expect(case.expect, chart)
    assert d.passed, _fmt_diff(d)


def test_gold002_box_third_buy_passes_gate(engine):
    """GOLD-002（北辰实业日线）：箱体三买代理产出唯一 bsp3@21（课文 11-14）。"""
    case = load_case(f"{GOLDEN_DIR}/gold-002.yaml")
    chart = engine.run(case.bars)
    assert [(b.idx, b.bstype, b.dir.value, b.level) for b in chart.bsp] == [
        (21, 3, "up", 1)
    ]
    d = diff_expect(case.expect, chart)
    assert d.passed, _fmt_diff(d)
