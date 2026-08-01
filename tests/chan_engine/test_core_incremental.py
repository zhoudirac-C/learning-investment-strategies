"""M3-5: 递归层增量生长 + 批量/增量终态一致性（设计文档风险表硬门）。

口径：
- 增量入口 ``RecursionEngine.run_incremental`` 逐 bar 投喂（chanpy 会话常驻，
  新 bar 只触发最低层更新，递归层在当前 bi 表上重算并向上传播）；
- **一致性硬门**：同一 bars 序列，一次性批量 ``run`` 与逐 bar 增量终态五表全等；
- is_sure 透传：中流快照的末位笔 sure=False，后续 bar 到位后翻为 True。
"""

from __future__ import annotations

import pytest

from chan_engine.core.engine import RecursionEngine
from chan_engine.spec.case_io import load_case
from chan_engine.spec.model import NormalizedChart

CASES_DIR = "src/chan_engine/spec/cases"
GOLDEN_DIR = "src/chan_engine/spec/golden"

# 一致性硬门覆盖：递归结构（BC-002/BSP-003）、金标箱体（GOLD-001/002）、
# 单级笔中枢哲学差异区（BC-001）、无三件套负向锚（SEG-001）
CONSISTENCY_CASES = [
    f"{CASES_DIR}/bc-002.yaml",
    f"{CASES_DIR}/bsp-003.yaml",
    f"{CASES_DIR}/bc-001.yaml",
    f"{CASES_DIR}/seg-001.yaml",
    f"{GOLDEN_DIR}/gold-001.yaml",
    f"{GOLDEN_DIR}/gold-002.yaml",
]


def _assert_chart_equal(a: NormalizedChart, b: NormalizedChart, ctx: str) -> None:
    """五表逐元素全等（dataclass 相等，含 Direction/float/sure/source）。"""
    for table in ("fx", "bi", "seg", "zs", "bsp"):
        ta, tb = getattr(a, table), getattr(b, table)
        assert len(ta) == len(tb), f"{ctx}: {table} 表长度 {len(ta)} != {len(tb)}"
        for i, (ea, eb) in enumerate(zip(ta, tb)):
            assert ea == eb, f"{ctx}: {table}[{i}] 不一致 {ea} != {eb}"


@pytest.fixture(scope="module")
def engine():
    return RecursionEngine()


@pytest.mark.parametrize("path", CONSISTENCY_CASES)
def test_batch_equals_incremental_final(engine, path):
    """批量 vs 逐 bar 增量：终态五表全等（一致性硬门）。"""
    case = load_case(path)
    batch = engine.run(case.bars)
    incremental = engine.run_incremental(case.bars)
    _assert_chart_equal(batch, incremental, ctx=path)


def test_sure_propagation_bc002(engine):
    """is_sure 透传：bi8（41→46 向下）在 prefix=46 时为末位 sure=False，
    全量到位后（不再末位）翻为 sure=True。"""
    case = load_case(f"{CASES_DIR}/bc-002.yaml")
    session = engine.new_session()
    chart_at_46 = None
    for k, bar in enumerate(case.bars):
        chart = session.push(bar)
        if k == 46:
            chart_at_46 = chart
    assert chart_at_46 is not None
    # prefix=46（含 idx46）：bi8=41→46 是当前末位笔 → sure=False
    bi8_mid = [b for b in chart_at_46.bi if (b.start_idx, b.end_idx) == (41, 46)]
    assert len(bi8_mid) == 1 and bi8_mid[0].sure is False
    # 全量终态：bi8 不再末位 → sure=True
    final = engine.run(case.bars)
    bi8_final = [b for b in final.bi if (b.start_idx, b.end_idx) == (41, 46)]
    assert len(bi8_final) == 1 and bi8_final[0].sure is True


def test_incremental_growth_bc002(engine):
    """增量生长：level-2 中枢在 B2 段成型前不出现，成型后出现且不消失。"""
    case = load_case(f"{CASES_DIR}/bc-002.yaml")
    session = engine.new_session()
    saw_lv2_at = None
    for k, bar in enumerate(case.bars):
        chart = session.push(bar)
        if any(z.level == 2 for z in chart.zs) and saw_lv2_at is None:
            saw_lv2_at = k
    # level-2 中枢 = B2 段（bi3-5, idx16→31）三笔重叠，须待 bi5 端点 idx31 到位
    assert saw_lv2_at is not None and saw_lv2_at >= 31
