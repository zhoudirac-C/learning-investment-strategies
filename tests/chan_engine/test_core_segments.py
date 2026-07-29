"""M3-1: L0 走势类型（线段）自建分组测试。

递归层不依赖适配器 seg 表（chanpy 对 BC-002 九笔并一段、czsc 无 seg），
从归一 bi 表 + bars 自行分组 L0 走势类型。

分组规则（以 expect 语料校准，逆向自 BC-002/SEG-001）：
- 贪婪取最小 3 笔段（段方向 = 首笔方向）；
- 沿段方向扩展：下一同向笔创出新极值（下跌段创新低 / 上涨段创新高）则吸收，
  否则段结束；
- 末尾不足 3 笔的残笔不成段（BC-002 余 bi9）。

锚定用例：
- BC-002：bi0-2(下) / bi3-5(上) / bi6-8(下)，余 bi9(unsure)；
- SEG-001：bi0-2(上) / bi3-5(下)；
- SEG-002：bi0-2(下) / bi3-5(上)。
"""

from __future__ import annotations

import pytest

from chan_engine.core.model import SegType
from chan_engine.core.segments import build_l0_segments
from chan_engine.spec.case_io import load_case
from chan_engine.spec.model import Bi, Direction

CASES_DIR = "src/chan_engine/spec/cases"


def _bi_list_from_expect(expect_bi: list[dict]) -> list[Bi]:
    """从用例 expect 的 bi 表构造 Bi 对象列表（递归层测试输入）。"""
    return [
        Bi(
            start_idx=b["start_idx"],
            end_idx=b["end_idx"],
            dir=Direction(b["dir"]),
            sure=b.get("sure", True),
            source="expect",
        )
        for b in expect_bi
    ]


def _seg_signature(segs: list[SegType]) -> list[tuple[int, int, str]]:
    return [(s.start_bi, s.end_bi, s.dir.value) for s in segs]


def test_bc002_l0_segments():
    case = load_case(f"{CASES_DIR}/bc-002.yaml")
    bi_list = _bi_list_from_expect(case.expect["bi"])
    segs = build_l0_segments(bi_list, case.bars)
    # A2=bi0-2 down, B2=bi3-5 up, C2=bi6-8 down；bi9(unsure) 不成段
    assert _seg_signature(segs) == [
        (0, 2, "down"),
        (3, 5, "up"),
        (6, 8, "down"),
    ]


def test_seg001_l0_segments():
    case = load_case(f"{CASES_DIR}/seg-001.yaml")
    bi_list = _bi_list_from_expect(case.expect["bi"])
    segs = build_l0_segments(bi_list, case.bars)
    assert _seg_signature(segs) == [(0, 2, "up"), (3, 5, "down")]


def test_seg002_l0_segments():
    case = load_case(f"{CASES_DIR}/seg-002.yaml")
    bi_list = _bi_list_from_expect(case.expect["bi"])
    segs = build_l0_segments(bi_list, case.bars)
    assert _seg_signature(segs) == [(0, 2, "down"), (3, 5, "up")]


def test_seg003_l0_segments():
    case = load_case(f"{CASES_DIR}/seg-003.yaml")
    bi_list = _bi_list_from_expect(case.expect["bi"])
    segs = build_l0_segments(bi_list, case.bars)
    assert _seg_signature(segs) == [(0, 2, "up"), (3, 5, "down")]


def test_segment_price_extremes_bc002():
    """段的高低价 = 段内全部笔的极值包络（供后续 3×L0 / 区间计算用）。"""
    case = load_case(f"{CASES_DIR}/bc-002.yaml")
    bi_list = _bi_list_from_expect(case.expect["bi"])
    segs = build_l0_segments(bi_list, case.bars)
    a2, b2, c2 = segs
    # B2（中枢段）区间须覆盖其内部 3 笔重叠区 [23.9, 26.2]
    assert b2.low <= 23.9 and b2.high >= 26.2
    # A2 为下跌段，末笔终点为段最低
    assert a2.dir is Direction.DOWN
    assert a2.low == pytest.approx(23.3)
    # C2 下跌段创新低（21.9）
    assert c2.low == pytest.approx(21.9)


def test_fewer_than_three_bi_no_segment():
    """不足 3 笔：无法成段，返回空。"""
    case = load_case(f"{CASES_DIR}/bc-002.yaml")
    bi_list = _bi_list_from_expect(case.expect["bi"])[:2]
    assert build_l0_segments(bi_list, case.bars) == []


def test_unsure_tail_bi_excluded_from_extension():
    """BC-002 末位 bi9(sure=False) 不应被并入 C2（段末端遇未确认笔停止）。"""
    case = load_case(f"{CASES_DIR}/bc-002.yaml")
    bi_list = _bi_list_from_expect(case.expect["bi"])
    segs = build_l0_segments(bi_list, case.bars)
    assert segs[-1].end_bi == 8  # C2 止于 bi8，不含 bi9
