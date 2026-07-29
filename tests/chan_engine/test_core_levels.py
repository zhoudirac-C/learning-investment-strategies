"""M3-2: LevelTree 多级中枢合成测试。

递归口径（课 35/84 + BC-002 expect 实证）：
- L0 段（走势类型）三件套：进入段(dir D) + 中枢段(dir ~D) + 离开段(dir D)；
- **中枢段** 的内部中枢 → 标记 level=2（它是 level-2 走势类型的中枢）；
- **离开段** 的内部中枢 → 标记 level=1（它是 level-1 走势类型的中枢，区间套次级别）；
- 段内中枢 = 连续三笔重叠区间（课 17：ZD=max(三笔低点)，ZG=min(三笔高点)）。

level-1 zd 校验：bi6/7/8 低点 = bars[36].l / bars[36].l / bars[46].l =
22.9 / 22.9 / 21.9，取 max = 22.9，与 expect 完全一致。
"""

from __future__ import annotations

import pytest

from chan_engine.core.levels import synthesize_level_zs
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
def bc002_zs():
    case = load_case(f"{CASES_DIR}/bc-002.yaml")
    bi_list = _bi_list(case)
    segs = build_l0_segments(bi_list, case.bars)
    return synthesize_level_zs(segs, bi_list, case.bars)


def test_bc002_emits_two_zs(bc002_zs):
    """BC-002：恰好两条中枢——level-2（中枢段 B2）+ level-1（离开段 C2）。"""
    assert len(bc002_zs) == 2
    levels = sorted(z.level for z in bc002_zs)
    assert levels == [1, 2]


def test_bc002_level2_zs(bc002_zs):
    """level-2 中枢 = 中枢段 B2（bi3-5）三笔重叠 [23.9, 26.2]，idx 16→31。"""
    lv2 = [z for z in bc002_zs if z.level == 2]
    assert len(lv2) == 1
    z = lv2[0]
    assert z.zd == pytest.approx(23.9)
    assert z.zg == pytest.approx(26.2)
    assert (z.start_idx, z.end_idx) == (16, 31)
    assert z.sure is True
    assert z.source == "recursion"


def test_bc002_level1_zs(bc002_zs):
    """level-1 中枢 = 离开段 C2（bi6-8）三笔重叠，idx 31→46，zd=22.9/zg=24.4。"""
    lv1 = [z for z in bc002_zs if z.level == 1]
    assert len(lv1) == 1
    z = lv1[0]
    assert (z.start_idx, z.end_idx) == (31, 46)
    assert z.zg == pytest.approx(24.4)
    # 课文中枢定义 ZD=max(三笔低点)=max(22.9,22.9,21.9)=22.9，与 expect 一致
    assert z.zd == pytest.approx(22.9)


def test_no_triple_no_zs():
    """无 进入+中枢+离开 三件套（段方向不成交替）→ 不出多级中枢。"""
    case = load_case(f"{CASES_DIR}/seg-001.yaml")
    bi_list = _bi_list(case)
    segs = build_l0_segments(bi_list, case.bars)
    # SEG-001 仅 2 段（up+down），不足三段 → 无 level-2
    zs = synthesize_level_zs(segs, bi_list, case.bars)
    assert [z for z in zs if z.level >= 2] == []
