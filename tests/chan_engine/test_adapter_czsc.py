"""Task 5: czsc 适配器测试。

用 builders 造一段确定走势（先盘后升，经验证 czsc 0.10.12 在其上产出 4 笔），
断言：
- FX/BI 表归一输出（数量、方向、端点 0 基下标、sure、source）；
- ZS 表存在且归一字段齐全；
- Segment/BSPoint 两表为空且 NormalizedChart.na_fields 标记 {"seg", "bsp"}；
- 配置快照记录影响口径的参数（版本、min_bi_len、max_bi_num、backend）。

注意：czsc 0.10.12 的 ``CZSC.fx_list`` 按 ``bi.fxs[1:]`` 拼接，会丢掉第一笔的
起始分型（本用例中 idx=5 的顶分型）——这是 czsc 的原生行为，适配器如实搬运，
作为对表时的口径差异暴露，不在适配器内补偿。
"""

from __future__ import annotations

import os

import pytest

from chan_engine.harness.adapter_czsc import CzscAdapter
from chan_engine.spec.builders import bars_from_closes
from chan_engine.spec.model import Direction, NormalizedChart

# 经验证（czsc 0.10.12，默认 min_bi_len=6）该序列产出 4 笔：
#   BI1: idx5 -> idx9  向下
#   BI2: idx9 -> idx13 向上
#   BI3: idx13 -> idx17 向下
#   BI4: idx17 -> idx23 向上
CLOSES = "10,11,12,13,14,13,12,11,10,11,12,13,14,13,12,11,10,11,12,13,14,15,16,15,14,13,12,11"

EXPECTED_BI = [
    (5, 9, Direction.DOWN),
    (9, 13, Direction.UP),
    (13, 17, Direction.DOWN),
    (17, 23, Direction.UP),
]

# czsc fx_list 不含第一笔的起始分型（顶@idx5），见模块 docstring。
EXPECTED_FX = [
    (9, Direction.DOWN),
    (13, Direction.UP),
    (17, Direction.DOWN),
    (23, Direction.UP),
]


@pytest.fixture()
def chart() -> NormalizedChart:
    adapter = CzscAdapter()
    return adapter.run(bars_from_closes(CLOSES))


def test_adapter_name_and_snapshot():
    adapter = CzscAdapter()
    assert adapter.name == "czsc"
    snap = adapter.config_snapshot
    assert isinstance(snap, dict)
    for key in ("czsc_version", "backend", "min_bi_len", "max_bi_num", "freq"):
        assert key in snap, f"config_snapshot 缺少 {key}"
    assert snap["czsc_version"] == "0.10.12"


def test_run_returns_normalized_chart(chart: NormalizedChart):
    assert isinstance(chart, NormalizedChart)


def test_bi_table(chart: NormalizedChart):
    assert len(chart.bi) == len(EXPECTED_BI)
    for bi, (s, e, d) in zip(chart.bi, EXPECTED_BI):
        assert (bi.start_idx, bi.end_idx, bi.dir) == (s, e, d)
        assert bi.sure is True
        assert bi.source == "czsc"


def test_fx_table(chart: NormalizedChart):
    assert len(chart.fx) == len(EXPECTED_FX)
    for fx, (i, d) in zip(chart.fx, EXPECTED_FX):
        assert (fx.idx, fx.type) == (i, d)
        assert fx.sure is True
        assert fx.source == "czsc"


def test_zs_table_exists_and_normalized(chart: NormalizedChart):
    assert isinstance(chart.zs, list)
    # 该输入下 4 笔重叠形成一个中枢（czsc get_zs_seq 实证输出）
    assert len(chart.zs) == 1
    zs = chart.zs[0]
    assert zs.zd == pytest.approx(9.5)
    assert zs.zg == pytest.approx(14.5)
    assert (zs.start_idx, zs.end_idx) == (5, 23)
    assert zs.level == 1
    assert zs.sure is True
    assert zs.source == "czsc"


def test_seg_bsp_marked_na(chart: NormalizedChart):
    assert chart.seg == []
    assert chart.bsp == []
    assert chart.na_fields == {"seg", "bsp"}


def test_indices_are_zero_based_positions(chart: NormalizedChart):
    n = len(bars_from_closes(CLOSES))
    for fx in chart.fx:
        assert isinstance(fx.idx, int) and 0 <= fx.idx < n
    for bi in chart.bi:
        assert 0 <= bi.start_idx < bi.end_idx < n


def test_short_input_no_bi():
    """不足成笔的短输入：bi/zs 为空，fx 可能存在但 sure=False，na_fields 不变。"""
    adapter = CzscAdapter()
    chart = adapter.run(bars_from_closes("10,11,12,13"))
    assert chart.bi == []
    assert chart.zs == []
    assert chart.na_fields == {"seg", "bsp"}
    for fx in chart.fx:
        assert fx.sure is False


# --- Fix: min_bi_len 快照失真（rust 后端忽略 czsc_min_bi_len）---

# 第一笔跨度恰好 6 根无包含 K 线：min_bi_len=6 成 2 笔，=7 则 0 笔（实证）
LEN_SENSITIVE_CLOSES = "10,11,12,13,14,15,14,13,12,11,12,13,14,15,16,17,16,15,14,13,12,11,10"


def test_nondefault_min_bi_len_takes_effect():
    """传非默认 min_bi_len 时输出必须真实变化（切换到 python 后端生效）。"""
    bars = bars_from_closes(LEN_SENSITIVE_CLOSES)
    default_chart = CzscAdapter().run(bars)
    strict_chart = CzscAdapter(min_bi_len=7).run(bars)
    assert len(default_chart.bi) == 2  # rust 后端内置 6，成 2 笔
    assert strict_chart.bi == []  # min_bi_len=7 真实生效：该走势不再成笔


def test_snapshot_requested_vs_effective():
    """快照如实区分 requested 与 effective，并记录后端切换原因。"""
    snap = CzscAdapter(min_bi_len=7).config_snapshot
    assert snap["backend"] == "python"
    assert snap["requested_min_bi_len"] == 7
    assert snap["effective_min_bi_len"] == 7
    assert snap["min_bi_len"] == 7  # 兼容 key = 实际生效值
    assert snap["backend_switch_reason"]


def test_default_path_snapshot_unchanged():
    """默认路径快照：rust 后端内置 6，未请求切换。"""
    snap = CzscAdapter().config_snapshot
    assert snap["backend"] == "rust"
    assert snap["requested_min_bi_len"] is None
    assert snap["effective_min_bi_len"] == 6
    assert snap["min_bi_len"] == 6
    assert snap["backend_switch_reason"] is None


def test_env_var_restored_after_run():
    """run() 结束后 czsc_min_bi_len 恢复原状，不留进程级污染。"""
    assert "czsc_min_bi_len" not in os.environ
    CzscAdapter(min_bi_len=7).run(bars_from_closes(LEN_SENSITIVE_CLOSES))
    assert "czsc_min_bi_len" not in os.environ
