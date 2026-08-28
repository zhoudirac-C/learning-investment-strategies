"""M7-4 区间套递归层（chanlun-m7-multitimeframe-skill.md §7）。

管线：日线归一图 + 次级别分钟行 → 全序列次级别引擎分解 → 窗口归属 →
SubLevelConfirmation（四输出：精确定位 / 背驰确认 / 中枢区间 / 二买确认 +
小转大候选标注）。

**全序列引擎 + 窗口归属**（2026-08-29 实证修正设计 §三"切片单独跑引擎"）：
切片孤跑丢失进入段上下文（512400 笔 [7/20~8/11] 的 60m 切片 68 根 → zs 全空），
无法复现 §1.1 结构；全序列引擎保留完整结构上下文，窗口只做归属
（zs span 与窗口相交即归入，bsp 按 idx 落窗）。探针记录见
docs/tasks/chanlun-m7-4-nested.md。
"""
from __future__ import annotations

from collections.abc import Callable

from chan_engine.core.backchi import _segment_area, _segment_area_macd
from chan_engine.core.levels import find_trend_patterns
from chan_engine.core.macd import calc_macd
from chan_engine.core.segments import build_l0_segments
from chan_engine.multi_tf.aligner import TFAligner
from chan_engine.multi_tf.model import (
    BiSlice,
    MultiTimeframeChart,
    SubLevelConfirmation,
    tf_minutes,
)
from chan_engine.spec.model import Bar, Bi, BSPoint, NormalizedChart


def _rows_to_bars(rows: list[dict]) -> list[Bar]:
    """归一分钟行 → 引擎 Bar（ts=行序，与 load_bars(tf) 同口径）。"""
    return [
        Bar(ts=i, o=float(r["open"]), h=float(r["high"]), l=float(r["low"]),
            c=float(r["close"]), vol=float(r["volume"]) if r["volume"] is not None else 0.0)
        for i, r in enumerate(rows)
    ]


def _dual_metric(
    sub_chart: NormalizedChart, bars: list[Bar], anchor_idx: int
) -> dict:
    """背驰双口径证据（§7.2）：锚点三件套 进入段/离开段 的 Σ|Δc| 与 MACD 面积。

    结论已按 MACD 主口径下（引擎默认）；此处并行输出对照证据。
    无匹配三件套 → 空 dict。
    """
    segments = build_l0_segments(sub_chart.bi, bars)
    patterns = find_trend_patterns(segments)
    for i0, _, i2 in reversed(patterns):
        s0, s2 = segments[i0], segments[i2]
        if sub_chart.bi[s2.end_bi].end_idx != anchor_idx:
            continue
        hist = calc_macd([b.c for b in bars])[2]
        return {
            "area_proxy": {
                "enter": _segment_area(s0, sub_chart.bi, bars),
                "leave": _segment_area(s2, sub_chart.bi, bars),
            },
            "macd_area": {
                "enter": _segment_area_macd(s0, sub_chart.bi, hist),
                "leave": _segment_area_macd(s2, sub_chart.bi, hist),
            },
        }
    return {}


def _confirm(
    daily: NormalizedChart,
    bi: Bi,
    s: BiSlice,
    sub_chart: NormalizedChart,
    bars: list[Bar],
) -> SubLevelConfirmation:
    """单根日线笔 × 单 tf 的区间套确认。"""
    lo, hi = s.start_pos, s.end_pos
    zs_in = sorted(
        (z for z in sub_chart.zs if z.start_idx < hi and z.end_idx >= lo),
        key=lambda z: (z.start_idx, z.end_idx),
    )
    bsp_in = sorted(
        (b for b in sub_chart.bsp if lo <= b.idx < hi),
        key=lambda b: (b.idx, b.bstype, -b.level),
    )

    # 次级别背驰 = 窗口内与日线笔反向的 bstype=1（笔末端反转确认信号）
    backchi_bsp = [b for b in bsp_in if b.bstype == 1 and b.dir is not bi.dir]
    backchi = bool(backchi_bsp)
    metric = _dual_metric(sub_chart, bars, backchi_bsp[-1].idx) if backchi else {}

    # 小转大候选（课 43）：次级别背驰 + 日线同位置无背驰买卖点 → 仅标注
    daily_div = any(
        b.bstype == 1 and b.idx == bi.end_idx and b.dir is not bi.dir
        for b in daily.bsp
    )
    small_to_large = backchi and not daily_div

    # 二买=次级别一买确认（买点定律）：日线二买/二卖候选落在本笔末端 →
    # 查窗口末段（最后 1 个交易日）是否存在同向次级别一买/一卖
    second = None
    daily_second = [b for b in daily.bsp
                    if b.bstype == 2 and b.idx == bi.end_idx]
    if daily_second and bsp_in:
        tail = hi - (240 // tf_minutes(s.tf))  # 窗口末段起点（60m 4 根/30m 8 根）
        second = any(
            b.bstype == 1 and b.dir is daily_second[0].dir and b.idx >= tail
            for b in bsp_in
        )
    elif daily_second:
        second = False

    return SubLevelConfirmation(
        bi_ref=(bi.start_idx, bi.end_idx),
        tf=s.tf,
        zs_in_bi=zs_in,
        bsp_in_bi=bsp_in,
        backchi=backchi,
        backchi_metric=metric,
        coverage=s.coverage,
        note=s.note,
        small_to_large=small_to_large,
        second_buy_confirmed=second,
    )


def analyze_nested(
    daily: NormalizedChart,
    daily_dates: list[str],
    sub_rows: dict[str, list[dict]],
    engine_factory: Callable[[str], object] | None = None,
) -> MultiTimeframeChart:
    """区间套递归管线：日线图 + 次级别行 → MultiTimeframeChart（含四输出确认）。

    ``sub_rows``：{'60m': rows, '30m': rows}（load_minute 归一行；构造 TFAligner
    时已剔除 complete=0 并做时段校验）。``engine_factory(tf)`` 返回带
    ``run(bars) -> NormalizedChart`` 的引擎（默认 RecursionEngine；测试可注入 stub）。
    次级别引擎对**全序列**运行（非切片孤跑，见模块 docstring 实证修正）。
    """
    if engine_factory is None:
        from chan_engine.core.engine import RecursionEngine

        engine_factory = lambda tf: RecursionEngine()  # noqa: E731

    aligner = TFAligner(daily_dates, sub_rows)
    sub_charts: dict[str, NormalizedChart] = {}
    sub_bars: dict[str, list[Bar]] = {}
    for label in sorted(aligner.sub_rows):
        rows = aligner.sub_rows[label]
        bars = _rows_to_bars(rows)
        sub_bars[label] = bars
        sub_charts[label] = engine_factory(label).run(bars) if bars else NormalizedChart()

    confirmations: list[SubLevelConfirmation] = []
    for bi in daily.bi:
        for label in sorted(aligner.sub_rows):
            s = aligner.slice_bi(bi, label)
            confirmations.append(
                _confirm(daily, bi, s, sub_charts[label], sub_bars[label]))

    return MultiTimeframeChart(
        daily=daily,
        sub=sub_charts,
        slices=aligner.slice_all(daily),
        confirmations=confirmations,
    )
