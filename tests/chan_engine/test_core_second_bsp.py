"""M7-3 G4：二买/二卖生成（课 17 二买定义 + 安全性证明）测试。

口径依据：chanlun-m7-multitimeframe-skill.md §6.3：
一买后**第一次次级别回调**（过渡期 = 反向笔代理，仲裁 ⑤；M7-4 起真 60m 确认）
低点不破一买低点 → 二买（bstype=2, dir=up）；一卖镜像。
sure 透传：回调笔未确认（sure=False）→ 二买候选 sure=False。
"""
from __future__ import annotations

from chan_engine.core.backchi import detect_second_type_bsp
from chan_engine.spec.model import Bar, Bi, BSPoint, Direction


def mkbar(i, h, l):
    mid = (h + l) / 2
    return Bar(ts=i, o=mid, h=h, l=l, c=mid, vol=1.0)


# bar 0..8；关键点：idx4 low=10.0（一买低点），idx6 low=10.5（回调低点，不破）
BARS = [
    mkbar(0, 13.0, 12.5), mkbar(1, 12.5, 12.0), mkbar(2, 12.0, 11.0),
    mkbar(3, 11.0, 10.2), mkbar(4, 10.4, 10.0), mkbar(5, 11.5, 10.3),
    mkbar(6, 11.2, 10.5), mkbar(7, 12.0, 10.8), mkbar(8, 12.5, 11.5),
]

# 一买@4 后的笔：4→5 上，5→6 下（回调），6→7 上
BI_AFTER_BUY = [
    Bi(start_idx=2, end_idx=4, dir=Direction.DOWN),   # 一买腿自身（start<4，不得被当回调）
    Bi(start_idx=4, end_idx=5, dir=Direction.UP),
    Bi(start_idx=5, end_idx=6, dir=Direction.DOWN),
    Bi(start_idx=6, end_idx=7, dir=Direction.UP),
]

BSP_1BUY = [BSPoint(idx=4, bstype=1, dir=Direction.UP, level=1)]
BSP_1SELL = [BSPoint(idx=4, bstype=1, dir=Direction.DOWN, level=1)]

# 一卖@4 后的笔：4→5 下，5→6 上（回抽）
BI_AFTER_SELL = [
    Bi(start_idx=2, end_idx=4, dir=Direction.UP),
    Bi(start_idx=4, end_idx=5, dir=Direction.DOWN),
    Bi(start_idx=5, end_idx=6, dir=Direction.UP),
    Bi(start_idx=6, end_idx=7, dir=Direction.DOWN),
]


class TestSecondBuy:
    def test_second_buy_holds_low(self):
        """二买构造例 1：一买后首次回调低点 10.5 > 一买低点 10.0 → 二买@6。"""
        out = detect_second_type_bsp(BSP_1BUY, BI_AFTER_BUY, BARS)
        assert len(out) == 1
        b = out[0]
        assert (b.idx, b.bstype, b.dir, b.level, b.sure) == (
            6, 2, Direction.UP, 1, True)

    def test_breaks_low_no_second_buy(self):
        """回调破一买低点 → 无二买（首次回调即破坏，一买失效候选）。"""
        bars = list(BARS)
        bars[6] = mkbar(6, 11.2, 9.8)  # 回调低点破 10.0
        assert detect_second_type_bsp(BSP_1BUY, BI_AFTER_BUY, bars) == []

    def test_counter_bi_unsure_propagates(self):
        """回调笔 sure=False → 二买候选 sure=False（右侧确认纪律透传）。"""
        bi = [BI_AFTER_BUY[0], BI_AFTER_BUY[1],
              Bi(start_idx=5, end_idx=6, dir=Direction.DOWN, sure=False)]
        out = detect_second_type_bsp(BSP_1BUY, bi, BARS)
        assert len(out) == 1 and out[0].sure is False

    def test_no_counter_bi_no_output(self):
        out = detect_second_type_bsp(BSP_1BUY, [BI_AFTER_BUY[0], BI_AFTER_BUY[1]], BARS)
        assert out == []

    def test_dual_level_first_buy_dedup_max_level(self):
        """同一买点被多级一买命中（L1+L2@46 形态）→ 单一二买取最高 level。"""
        bsp = [BSPoint(idx=4, bstype=1, dir=Direction.UP, level=2),
               BSPoint(idx=4, bstype=1, dir=Direction.UP, level=1)]
        out = detect_second_type_bsp(bsp, BI_AFTER_BUY, BARS)
        assert len(out) == 1 and out[0].level == 2

    def test_third_type_ignored(self):
        """三类买卖点不产生二买。"""
        bsp = [BSPoint(idx=4, bstype=3, dir=Direction.UP, level=1)]
        assert detect_second_type_bsp(bsp, BI_AFTER_BUY, BARS) == []


class TestSecondSell:
    def test_second_sell_holds_high(self):
        """二卖构造例 2（镜像）：一卖后首次回抽高点不破一卖高点 → 二卖@6。"""
        # bars[4].h = 10.4 为一卖高点；回抽笔终点 bars[6].h = 11.2 会破——
        # 构造专用 bars：一卖高点 12.0，回抽高点 11.6
        bars = [
            mkbar(0, 10.0, 9.5), mkbar(1, 10.5, 10.0), mkbar(2, 11.0, 10.5),
            mkbar(3, 11.8, 11.0), mkbar(4, 12.0, 11.2), mkbar(5, 11.4, 10.6),
            mkbar(6, 11.6, 11.0), mkbar(7, 11.0, 10.2), mkbar(8, 10.5, 10.0),
        ]
        out = detect_second_type_bsp(BSP_1SELL, BI_AFTER_SELL, bars)
        assert len(out) == 1
        b = out[0]
        assert (b.idx, b.bstype, b.dir, b.level, b.sure) == (
            6, 2, Direction.DOWN, 1, True)

    def test_breaks_high_no_second_sell(self):
        bars = [
            mkbar(0, 10.0, 9.5), mkbar(1, 10.5, 10.0), mkbar(2, 11.0, 10.5),
            mkbar(3, 11.8, 11.0), mkbar(4, 12.0, 11.2), mkbar(5, 11.4, 10.6),
            mkbar(6, 12.2, 11.0),  # 回抽破 12.0
        ]
        assert detect_second_type_bsp(BSP_1SELL, BI_AFTER_SELL, bars) == []


class TestEngineIntegration:
    def test_bc002_no_second_buy_no_regression(self):
        """BC-002 一买@46 后无确认反向笔 → 不二买，既有输出不变（§6.5 零回归）。"""
        from chan_engine.core.engine import RecursionEngine
        from chan_engine.spec.case_io import load_case

        case = load_case("src/chan_engine/spec/cases/bc-002.yaml")
        chart = RecursionEngine().run(case.bars)
        assert [b for b in chart.bsp if b.bstype == 2] == []
        assert len(chart.bsp) == 2  # 双级别一买@46，不多不少
