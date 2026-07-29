"""M3-3: 背驰判断 + 多级买卖点测试。

背驰口径（BC-002 expect + 课 27 区间套实证）：
- 面积代理 = 段内全部笔 |收盘变化| 之和（Σ|Δc|）；
- **level-2 背驰**：进入段面积 vs 离开段面积，离开 < 进入 → 大级别背驰 →
  一买/一卖（离开段终点，level=2）。BC-002：A2=10.84 > C2=6.04 → level-2 一买@46；
- **level-1 背驰**：离开段内 首同向笔 vs 末同向笔，末 < 首 → 次级别背驰 →
  一买/一卖（离开段终点，level=1）。BC-002：a1=2.88 > c1=2.08 → level-1 一买@46；
- 买卖点方向：下跌走势背驰 → 一买 dir=up；上涨走势背驰 → 一卖 dir=down。
"""

from __future__ import annotations

import pytest

from chan_engine.core.backchi import detect_backchi_bsp
from chan_engine.core.segments import build_l0_segments
from chan_engine.spec.case_io import load_case
from chan_engine.spec.model import Bi, Direction

CASES_DIR = "src/chan_engine/spec/cases"


def _bi_list(case) -> list[Bi]:
    return [
        Bi(
            start_idx=b["start_idx"],
            end_idx=b["end_idx"],
            dir=Direction(b["dir"]),
            sure=b.get("sure", True),
            source="expect",
        )
        for b in case.expect["bi"]
    ]


@pytest.fixture()
def bc002_bsp():
    case = load_case(f"{CASES_DIR}/bc-002.yaml")
    bi_list = _bi_list(case)
    segs = build_l0_segments(bi_list, case.bars)
    return detect_backchi_bsp(segs, bi_list, case.bars)


def test_bc002_dual_level_bsp1(bc002_bsp):
    """BC-002 区间套：同一 idx=46 双级别一买（level=2 与 level=1 各一）。"""
    bsp1 = [(b.idx, b.level) for b in bc002_bsp if b.bstype == 1]
    assert (46, 2) in bsp1
    assert (46, 1) in bsp1


def test_bc002_bsp1_direction_and_sure(bc002_bsp):
    """一买方向 up、形成即确认 sure=True、source=recursion。"""
    for b in bc002_bsp:
        assert b.dir is Direction.UP  # 下跌走势背驰 → 一买
        assert b.sure is True
        assert b.source == "recursion"
        assert b.idx == 46


def test_bc002_bsp_count(bc002_bsp):
    """BC-002 恰好两条买卖点（level-2 + level-1 一买）。"""
    assert len(bc002_bsp) == 2


def test_no_backchi_no_bsp():
    """无背驰（离开段面积 > 进入段）→ 不出买卖点。

    构造：进入段短（面积小）、离开段长（面积大），不构成背驰。
    """
    case = load_case(f"{CASES_DIR}/seg-001.yaml")
    bi_list = _bi_list(case)
    segs = build_l0_segments(bi_list, case.bars)
    # SEG-001 仅 2 段，无三件套 → 无买卖点
    assert detect_backchi_bsp(segs, bi_list, case.bars) == []
