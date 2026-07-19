"""Task 4: chan.py 适配器测试。

用显式 (o,h,l,c) 造一段确定 zigzag 走势：顶分型@bar2 → 底分型@bar6 → 顶分型@bar10，
相邻 K 线均无包含关系，严格笔跨度=4（满足 chan.py 默认 bi_strict 口径），
预期恰好 2 笔：DOWN(2→6)、UP(6→10)。
"""

from chan_engine.harness.adapter import ChartAdapter
from chan_engine.harness.adapter_chanpy import ChanPyAdapter
from chan_engine.spec.builders import bars_from_ohlc
from chan_engine.spec.model import Direction

# 13 根 K 线：bar2 顶(h=4.6) → bar6 底(l=0.4) → bar10 顶(h=4.6)，尾部 2 根不足以成第 3 笔。
ZIGZAG_OHLC = [
    (2.0, 2.6, 1.8, 2.5),  # 0
    (2.5, 3.6, 2.4, 3.5),  # 1
    (3.5, 4.6, 3.5, 4.5),  # 2 顶分型
    (4.5, 4.5, 3.4, 3.5),  # 3
    (3.5, 3.5, 2.4, 2.5),  # 4
    (2.5, 2.5, 1.4, 1.5),  # 5
    (1.5, 1.5, 0.4, 0.5),  # 6 底分型
    (0.5, 1.6, 0.5, 1.5),  # 7
    (1.5, 2.6, 1.5, 2.5),  # 8
    (2.5, 3.6, 2.5, 3.5),  # 9
    (3.5, 4.6, 3.5, 4.5),  # 10 顶分型
    (4.5, 4.5, 3.4, 3.5),  # 11
    (3.5, 3.5, 2.4, 2.5),  # 12
]


def make_adapter() -> ChanPyAdapter:
    return ChanPyAdapter()


class TestChanPyAdapterProtocol:
    def test_conforms_to_chart_adapter_protocol(self):
        adapter = make_adapter()
        assert isinstance(adapter, ChartAdapter)
        assert adapter.name == "chanpy"

    def test_config_snapshot_fields(self):
        snapshot = make_adapter().config_snapshot
        assert isinstance(snapshot, dict)
        for key in ("trigger_step", "bi", "seg", "zs", "bsp"):
            assert key in snapshot, f"config_snapshot 缺字段 {key}"
        # 关键默认配置项（偏差分析要用）
        assert snapshot["trigger_step"] is True  # 逐帧投喂所需的唯一非默认项
        assert snapshot["bi"]["is_strict"] is True
        assert snapshot["bi"]["bi_fx_check"] == "STRICT"
        assert snapshot["bi"]["bi_end_is_peak"] is True
        assert snapshot["seg"]["seg_algo"] == "chan"
        assert snapshot["zs"]["zs_algo"] == "normal"
        assert snapshot["bsp"]["min_zs_cnt"] == 1


class TestChanPyAdapterRun:
    def test_two_bi_zigzag(self):
        bars = bars_from_ohlc(ZIGZAG_OHLC)
        chart = make_adapter().run(bars)

        # 笔：恰好 2 笔，方向 DOWN→UP，端点为分型所在 bar 的 0 基下标
        assert len(chart.bi) == 2
        assert [bi.dir for bi in chart.bi] == [Direction.DOWN, Direction.UP]
        assert (chart.bi[0].start_idx, chart.bi[0].end_idx) == (2, 6)
        assert (chart.bi[1].start_idx, chart.bi[1].end_idx) == (6, 10)

        # 分型：3 个，顶@2 / 底@6 / 顶@10（type: UP=顶, DOWN=底）
        assert len(chart.fx) == 3
        assert [fx.idx for fx in chart.fx] == [2, 6, 10]
        assert [fx.type for fx in chart.fx] == [Direction.UP, Direction.DOWN, Direction.UP]

        # sure 标记为 bool；首笔已被第二笔确认
        assert chart.bi[0].sure is True
        assert isinstance(chart.bi[1].sure, bool)
        assert all(isinstance(fx.sure, bool) for fx in chart.fx)

        # 五表齐全；2 笔不足以成段/中枢/买卖点，这三表应为空列表
        assert chart.seg == []
        assert chart.zs == []
        assert chart.bsp == []
        assert chart.na_fields == set()

        # source 与索引口径
        for table in (chart.fx, chart.bi):
            for elem in table:
                assert elem.source == "chanpy"
        for bi in chart.bi:
            assert 0 <= bi.start_idx < len(bars)
            assert 0 <= bi.end_idx < len(bars)

    def test_run_is_deterministic(self):
        bars = bars_from_ohlc(ZIGZAG_OHLC)
        adapter = make_adapter()
        first = adapter.run(bars)
        second = adapter.run(bars)
        assert first == second
