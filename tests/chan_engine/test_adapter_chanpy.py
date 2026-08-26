"""Task 4: chan.py 适配器测试（M2-1 起含归一约定覆盖）。

用显式 (o,h,l,c) 造一段确定 zigzag 走势：顶分型@bar2 → 底分型@bar6 → 顶分型@bar10，
相邻 K 线均无包含关系，严格笔跨度=4（满足 chan.py 默认 bi_strict 口径），
预期恰好 2 笔：DOWN(2→6)、UP(6→10)。

M2-1 新增覆盖：sure 位置约定（fx/bi/seg 末位 False 其余 True，zs/bsp 恒 True）、
fx 从 CKLine.fx 标记直取（孤立分型入表、合并 K 线 idx 取极值 klu、被取代分型过滤）、
bsp dir=操作方向（买点=UP）、默认配置 bi_fx_check=loss 进快照。
"""

from pathlib import Path

from Common.CEnum import BSP_TYPE

from chan_engine.harness.adapter import ChartAdapter
from chan_engine.harness.adapter_chanpy import ChanPyAdapter, _distinct_main_types
from chan_engine.spec.builders import bars_from_ohlc
from chan_engine.spec.case_io import load_case
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
        assert snapshot["trigger_step"] is True  # 逐帧投喂所需的非默认项
        assert snapshot["bi"]["is_strict"] is True
        assert snapshot["bi"]["bi_fx_check"] == "LOSS"  # M2-1：strict→loss（ADR-001 口径 B）
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

        # sure 位置约定（M2-1）：fx/bi 末位 False、其余 True
        assert [bi.sure for bi in chart.bi] == [True, False]
        assert [fx.sure for fx in chart.fx] == [True, True, False]

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


# --- M2-1 归一约定测试数据（构造取自 spec 用例，注释标明验证点） ---

# FX-002 同款：右侧刚走完一个顶分型（bar0-2），其后无任何 K 线 → 孤立分型，不成笔。
FX_002_OHLC = [
    (10.0, 10.6, 9.8, 10.4),
    (10.4, 11.2, 10.2, 11.0),
    (10.7, 10.8, 10.1, 10.4),
]

# FX-003 同款：bar2 被 bar1 包含、向上合并，顶分型极值（高 11.3）来自原始 bar2。
FX_003_OHLC = [
    (10.0, 10.4, 9.6, 10.1),
    (10.1, 11.0, 9.9, 10.7),
    (10.7, 11.3, 9.8, 10.4),
    (10.4, 10.9, 9.7, 10.6),
]

# INCLUDE-001 同款：bar2 被 bar1 包含、向上合并，顶分型极值（高 11.6）来自原始 bar1。
INCLUDE_001_OHLC = [
    (10.0, 11.0, 9.5, 10.8),
    (10.8, 11.6, 10.2, 11.4),
    (11.1, 11.2, 10.6, 10.8),
    (10.8, 11.0, 9.8, 9.9),
]

# BI-004 同款：旧顶@5 未被反向笔确认、被更高顶@9 取代（课77 步骤二"X 掉"）；
# bar6 底分型距顶@5 过近不可能成笔——两个被消解的分型都不得进 fx 表。
BI_004_OHLC = [
    (10.4, 10.7, 10.0, 10.2),
    (10.2, 10.3, 9.5, 9.8),
    (9.8, 10.6, 9.7, 10.4),
    (10.4, 11.0, 10.2, 10.8),
    (10.8, 11.4, 10.6, 11.1),
    (11.1, 11.7, 11.0, 11.4),
    (11.4, 11.5, 10.9, 11.2),
    (11.2, 11.6, 11.0, 11.4),
    (11.4, 12.0, 11.2, 11.8),
    (11.8, 12.3, 11.7, 12.0),
    (12.0, 12.1, 11.5, 11.7),
]

# BI-005 同款：标准两笔（顶@5 已被反向笔确认，底@9 未确认）。
BI_005_OHLC = [
    (10.4, 10.7, 10.0, 10.2),
    (10.2, 10.3, 9.5, 9.8),
    (9.8, 10.5, 9.7, 10.3),
    (10.3, 10.9, 10.1, 10.7),
    (10.7, 11.3, 10.5, 11.0),
    (11.0, 11.8, 10.9, 11.4),
    (11.4, 11.5, 10.4, 10.7),
    (10.7, 10.8, 10.0, 10.2),
    (10.2, 10.4, 9.6, 9.9),
    (9.9, 10.1, 9.2, 9.5),
    (9.5, 10.4, 9.4, 10.2),
]

# SEG-001 同款：六笔两段，末段未被反向线段破坏。
SEG_001_OHLC = [
    (10.945, 11.05, 10.7, 10.805),
    (10.105, 10.35, 10.0, 10.245),
    (10.6395, 10.8845, 10.5345, 10.7795),
    (11.93, 12.175, 11.825, 12.07),
    (13.2205, 13.4655, 13.1155, 13.3605),
    (13.755, 14.0, 13.65, 13.895),
    (13.6534, 13.7584, 13.4084, 13.5134),
    (13.07, 13.175, 12.825, 12.93),
    (12.4866, 12.5916, 12.2416, 12.3466),
    (12.245, 12.35, 12.0, 12.105),
    (12.6395, 12.8845, 12.5345, 12.7795),
    (13.93, 14.175, 13.825, 14.07),
    (15.2205, 15.4655, 15.1155, 15.3605),
    (15.755, 16.0, 15.65, 15.895),
    (15.5069, 15.6119, 15.2619, 15.3669),
    (14.57, 14.675, 14.325, 14.43),
    (13.6331, 13.7381, 13.3881, 13.4931),
    (13.245, 13.35, 13.0, 13.105),
    (13.3466, 13.5916, 13.2416, 13.4866),
    (13.93, 14.175, 13.825, 14.07),
    (14.5134, 14.7584, 14.4084, 14.6534),
    (14.755, 15.0, 14.65, 14.895),
    (14.3605, 14.4655, 14.1155, 14.2205),
    (13.07, 13.175, 12.825, 12.93),
    (11.7795, 11.8845, 11.5345, 11.6395),
    (11.245, 11.35, 11.0, 11.105),
    (11.805, 12.05, 11.7, 11.945),
]

# BSP-001 同款：下跌五笔 + 中枢 + 一买@26。
BSP_001_OHLC = [
    (22.67, 22.9, 22.12, 22.35),
    (23.44, 24.0, 23.2, 23.76),
    (22.35, 22.9, 22.12, 22.67),
    (21.27, 21.8, 21.04, 21.57),
    (20.18, 20.7, 19.96, 20.48),
    (19.1, 19.6, 18.88, 19.38),
    (18.29, 18.5, 17.8, 18.01),
    (18.43, 18.92, 18.22, 18.71),
    (18.85, 19.34, 18.64, 19.13),
    (19.27, 19.76, 19.06, 19.55),
    (19.69, 20.18, 19.48, 19.97),
    (20.11, 20.6, 19.9, 20.39),
    (19.79, 20.28, 19.58, 20.07),
    (19.47, 19.96, 19.26, 19.75),
    (19.15, 19.64, 18.94, 19.43),
    (18.83, 19.32, 18.62, 19.11),
    (18.79, 19.0, 18.3, 18.51),
    (18.75, 19.24, 18.54, 19.03),
    (18.99, 19.48, 18.78, 19.27),
    (19.23, 19.72, 19.02, 19.51),
    (19.47, 19.96, 19.26, 19.75),
    (19.71, 20.2, 19.5, 19.99),
    (19.19, 19.68, 18.98, 19.47),
    (18.67, 19.16, 18.46, 18.95),
    (18.15, 18.64, 17.94, 18.43),
    (17.63, 18.12, 17.42, 17.91),
    (17.39, 17.6, 16.9, 17.11),
    (17.37, 17.86, 17.16, 17.65),
    (17.63, 18.12, 17.42, 17.91),
    (17.89, 18.38, 17.68, 18.17),
    (18.15, 18.64, 17.94, 18.43),
    (18.41, 18.9, 18.2, 18.69),
    (18.43, 18.64, 17.94, 18.15),
]


class TestChanPyAdapterNormalization:
    """M2-1 归一约定：fx 直取 + sure 位置约定 + bsp dir=操作方向。"""

    def test_isolated_fx_without_bi(self):
        """无笔时孤立分型从 CKLine.fx 标记直取入表；单元素即末位 → sure=False。"""
        chart = make_adapter().run(bars_from_ohlc(FX_002_OHLC))
        assert [(fx.idx, fx.type, fx.sure) for fx in chart.fx] == [
            (1, Direction.UP, False),
        ]
        assert chart.bi == []

    def test_fx_idx_maps_to_extreme_klu_of_merged_kline(self):
        """合并 K 线上的分型，idx 取极值所在原始 klu（顶取最高高所在子 klu）。"""
        chart = make_adapter().run(bars_from_ohlc(FX_003_OHLC))
        assert [(fx.idx, fx.type, fx.sure) for fx in chart.fx] == [
            (2, Direction.UP, False),
        ]
        chart = make_adapter().run(bars_from_ohlc(INCLUDE_001_OHLC))
        assert [(fx.idx, fx.type, fx.sure) for fx in chart.fx] == [
            (1, Direction.UP, False),
        ]

    def test_replaced_fx_filtered_to_bi_endpoints(self):
        """被更高顶取代的顶@5 与过近不成笔的底@6 不进 fx 表（课77 步骤二/三）。"""
        chart = make_adapter().run(bars_from_ohlc(BI_004_OHLC))
        assert [(fx.idx, fx.type, fx.sure) for fx in chart.fx] == [
            (1, Direction.DOWN, True),
            (9, Direction.UP, False),
        ]
        assert [(bi.start_idx, bi.end_idx, bi.dir, bi.sure) for bi in chart.bi] == [
            (1, 9, Direction.UP, False),
        ]

    def test_bi_fx_sure_position_convention(self):
        """多笔：fx/bi 表末位 sure=False、其余 True。"""
        chart = make_adapter().run(bars_from_ohlc(BI_005_OHLC))
        assert [bi.sure for bi in chart.bi] == [True, False]
        assert [fx.sure for fx in chart.fx] == [True, True, False]

    def test_seg_sure_position_convention(self):
        """seg 表同位置约定：末位（未被破坏）False、其余 True。"""
        chart = make_adapter().run(bars_from_ohlc(SEG_001_OHLC))
        assert [(seg.start_bi, seg.end_bi, seg.dir, seg.sure) for seg in chart.seg] == [
            (0, 2, Direction.UP, True),
            (3, 5, Direction.DOWN, False),
        ]

    def test_bsp_dir_is_operation_direction(self):
        """bsp dir=操作方向（ADR-006）：买点→UP；zs/bsp 形成即 sure=True。"""
        chart = make_adapter().run(bars_from_ohlc(BSP_001_OHLC))
        assert [(b.idx, b.bstype, b.dir, b.level, b.sure) for b in chart.bsp] == [
            (26, 1, Direction.UP, 1, True),
        ]
        assert [(z.zd, z.zg, z.start_idx, z.end_idx, z.level, z.sure) for z in chart.zs] == [
            (18.3, 20.2, 6, 21, 1, True),
        ]


_CASES_DIR = Path(__file__).resolve().parents[2] / "src" / "chan_engine" / "spec" / "cases"


class TestMultiMainTypeBsp:
    """M5-1：同笔多类型买卖点按 distinct main_type 逐条出记录（课21 二三类重合）。

    依据：M4 评估 §2——chanpy 内部已算出 bsp@klu36 types=[T2, T3B]，
    旧提取口径 bsp.type[0] 丢弃 T3B。
    """

    def test_bsp004_second_and_third_buy_coincide(self):
        case = load_case(_CASES_DIR / "bsp-004.yaml")
        chart = make_adapter().run(case.bars)
        assert [(b.idx, b.bstype, b.dir, b.level, b.sure) for b in chart.bsp] == [
            (26, 1, Direction.UP, 1, True),
            (36, 2, Direction.UP, 1, True),
            (36, 3, Direction.UP, 1, True),
        ]

    def test_distinct_main_types_dedup(self):
        """同 main_type 去重（T1/T1P 理论可同挂一笔，M4-2 评审提示）；保持原顺序。"""
        assert _distinct_main_types([BSP_TYPE.T2, BSP_TYPE.T3B]) == [2, 3]
        assert _distinct_main_types([BSP_TYPE.T1, BSP_TYPE.T1P]) == [1]
        assert _distinct_main_types([BSP_TYPE.T3A]) == [3]
