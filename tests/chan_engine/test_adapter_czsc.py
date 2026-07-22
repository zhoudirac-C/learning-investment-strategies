"""Task 5: czsc 适配器测试（M2-2 起含首分型补偿 + zs 重算 + 位置约定覆盖）。

用 builders 造一段确定走势（先盘后升，经验证 czsc 0.10.12 在其上产出 4 笔），
断言：
- FX/BI 表归一输出（数量、方向、端点 0 基下标、sure、source）；
- ZS 表存在且归一字段齐全（M2-2：按 chanpy normal 模式重算，start_idx=反向笔a起点）；
- Segment/BSPoint 两表为空且 NormalizedChart.na_fields 标记 {"seg", "bsp"}；
- 配置快照记录影响口径的参数（版本、min_bi_len、max_bi_num、backend）。

M2-2 改造覆盖：
- 首分型补偿：``bi_list[0].fx_a`` 补一条 FX（不再丢第一笔起始分型）；
- fx 从 bi 端点推导（不再用 ``c.fx_list``，规避 BI-004 多余分型问题）；
- zs 重算：弃用 ``get_zs_seq``，按 chanpy normal 模式（反向笔 + in_range 延伸）；
- 位置约定：fx/bi 表末位 sure=False、其余 True（与 chanpy 适配器同口径）。
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

# M2-2：首分型补偿后 fx 表 = 首笔起点 + 每笔终点（5 个）。
# 位置约定：末位（bi4 终点 idx=23）sure=False，其余 True。
EXPECTED_FX = [
    (5, Direction.UP),
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
    # M2-2 标记：zs 重算口径 + fx 来源
    assert snap["zs_recompute"] == "chanpy_normal_mode"
    assert snap["fx_source"] == "bi_endpoints"


def test_run_returns_normalized_chart(chart: NormalizedChart):
    assert isinstance(chart, NormalizedChart)


def test_bi_table(chart: NormalizedChart):
    assert len(chart.bi) == len(EXPECTED_BI)
    # M2-2 位置约定：末位（bi4 未确认）sure=False，其余 True
    expected_sure = [True, True, True, False]
    for bi, (s, e, d), sure in zip(chart.bi, EXPECTED_BI, expected_sure):
        assert (bi.start_idx, bi.end_idx, bi.dir) == (s, e, d)
        assert bi.sure is sure
        assert bi.source == "czsc"


def test_fx_table(chart: NormalizedChart):
    assert len(chart.fx) == len(EXPECTED_FX)
    # M2-2 位置约定：末位（bi4 终点分型）sure=False，其余 True
    expected_sure = [True, True, True, True, False]
    for fx, (i, d), sure in zip(chart.fx, EXPECTED_FX, expected_sure):
        assert (fx.idx, fx.type) == (i, d)
        assert fx.sure is sure
        assert fx.source == "czsc"


def test_zs_table_exists_and_normalized(chart: NormalizedChart):
    assert isinstance(chart.zs, list)
    # M2-2：按 chanpy normal 模式重算。
    # 引导笔 bi0=5→9 down（seg_dir=DOWN），反向笔=up笔=bi1(9→13)/bi3(17→23)。
    # bi1 [9.5, 14.5] 与 bi3 [9.5, 16.5] 严格重叠 → 构造中枢
    #   zd=max(9.5, 9.5)=9.5, zg=min(14.5, 16.5)=14.5
    #   start=bi1.start_idx=9, end=bi3.end_idx=23
    assert len(chart.zs) == 1
    zs = chart.zs[0]
    assert zs.zd == pytest.approx(9.5)
    assert zs.zg == pytest.approx(14.5)
    assert (zs.start_idx, zs.end_idx) == (9, 23)
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
