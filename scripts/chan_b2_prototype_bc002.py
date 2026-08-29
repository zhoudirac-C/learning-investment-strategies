#!/usr/bin/env python
"""B-2 单点原型：fx 段内笔级重释能否重构 BC-002 区间套（ADR-012 方案 B 演进验证）。

背景：B-3 影子证据（logs/chan-fx-shadow-20260829.md）表明递归层直接切 fx 段后
BC-002 区间套断供（fx 九并一 → zs/bsp 零产出）。本原型验证 B-2 路线：
**不拆 fx 段，在段内用笔级"创新极值/未创新极值"重构 进入-中枢-离开 结构**。

规则（DOWN 段，UP 镜像）：
1. 段内同向笔（DOWN 段的向下笔）分类：创段方向新极值 → 推动笔；未创 → 修正笔。
2. 修正笔极大连续run → 中枢候选，span = 首根修正笔前的反向笔 .. 末根修正笔后的反向笔
   （BC-002：修正笔 bi4 → span bi3-5）。
3. 中枢成立 = span 首三笔严格重叠（课 17），后续已确认笔严格重叠则延伸
   （同 core/levels._segment_zhongshu 口径）。
4. 进入腿 = 段首..中枢前；离开腿 = 中枢后..段尾（尾部未确认笔剔除，同 greedy 纪律）。
5. 背驰：area(离开腿) < area(进入腿) → 段级一买/一卖（σ 与 MACD 双口径）；
   离开腿内首末同向笔面积 → 次级别一买/一卖；离开腿首三笔重叠 → 次级别中枢。

验证锚（BC-002 expect）：
- 中枢 [23.9, 26.2] @16→31（expect 标 level=2，greedy 三件套口径）；
- 次级别中枢 [22.9, 24.4] @31→46（expect 标 level=1）；
- 双级别一买 @46（σ 口径 10.84>6.04、2.88>2.08；MACD 口径同向）。

用法（仓根）：
    PYTHONPATH=src:third_party/chanpy .venv/bin/python scripts/chan_b2_prototype_bc002.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "third_party" / "chanpy"))

from chan_engine.core.macd import calc_macd
from chan_engine.core.segments import _bi_high_low
from chan_engine.core.segments_fx import build_fx_segments
from chan_engine.harness.adapter_chanpy import ChanPyAdapter
from chan_engine.spec.case_io import load_case
from chan_engine.spec.model import Direction


def _new_extreme(cur: float, running: float, seg_dir: Direction) -> bool:
    return cur < running if seg_dir is Direction.DOWN else cur > running


def _bi_area_sigma(bi, bars) -> float:
    return abs(float(bars[bi.end_idx].c) - float(bars[bi.start_idx].c))


def _span_area_sigma(positions, bi_list, bars) -> float:
    return sum(_bi_area_sigma(bi_list[k], bars) for k in positions)


def _span_area_macd(positions, bi_list, hist) -> float:
    start = bi_list[positions[0]].start_idx
    end = bi_list[positions[-1]].end_idx
    return sum(abs(hist[i]) for i in range(start, end + 1))


def _bi_area_macd(bi, hist) -> float:
    return sum(abs(hist[i]) for i in range(bi.start_idx, bi.end_idx + 1))


def split_structure(seg, bi_list, bars):
    """fx 段内笔级结构拆分：→ (中枢 span, 进入腿, 离开腿)，不成立返回 None。"""
    pos = list(range(seg.start_bi, seg.end_bi + 1))
    while pos and not bi_list[pos[-1]].sure:
        pos.pop()  # 尾部未确认笔剔除（greedy"残笔不成段"同纪律）
    seg_dir_positions = [k for k in pos if bi_list[k].dir is seg.dir]

    running = None
    corrective: list[int] = []
    for k in seg_dir_positions:
        bar = bars[bi_list[k].end_idx]
        cur = bar.l if seg.dir is Direction.DOWN else bar.h
        if running is None or _new_extreme(cur, running, seg.dir):
            running = cur
            if corrective:
                break  # 只取第一个中枢候选（单点原型；多中枢趋势泛化另议）
        else:
            corrective.append(k)
    if not corrective:
        return None
    zs_start = corrective[0] - 1  # 首根修正笔前的反向笔
    zs_end = corrective[-1] + 1  # 末根修正笔后的反向笔
    if zs_start < seg.start_bi or zs_end > pos[-1]:
        return None
    enter = [k for k in pos if k < zs_start]
    leave = [k for k in pos if k > zs_end]
    if not enter or not leave:
        return None
    return (list(range(zs_start, zs_end + 1)), enter, leave)


def zs_from_span(span, bi_list, bars):
    """span 首三笔严格重叠中枢（课 17）+ 已确认笔延伸（_segment_zhongshu 口径）。"""
    if len(span) < 3:
        return None
    seed = span[:3]
    zd = max(_bi_high_low(bi_list[k], bars)[0] for k in seed)
    zg = min(_bi_high_low(bi_list[k], bars)[1] for k in seed)
    if zg <= zd:
        return None
    end_idx = bi_list[seed[-1]].end_idx
    for k in span[3:]:
        lo, hi = _bi_high_low(bi_list[k], bars)
        if not bi_list[k].sure or not (hi > zd and zg > lo):
            break
        end_idx = bi_list[k].end_idx
    return {
        "zd": round(zd, 2), "zg": round(zg, 2),
        "start": bi_list[seed[0]].start_idx, "end": end_idx,
    }


def main() -> None:
    case = load_case(REPO / "src/chan_engine/spec/cases/bc-002.yaml")
    bi = ChanPyAdapter().run(case.bars).bi
    fx_segs = build_fx_segments(bi, case.bars)
    assert len(fx_segs) == 1, f"BC-002 前置：fx 应九并一，实际 {len(fx_segs)} 段"
    seg = fx_segs[0]
    print(f"fx 段: bi{seg.start_bi}-{seg.end_bi} {seg.dir.name} sure={seg.sure}\n")

    result = split_structure(seg, bi, case.bars)
    assert result is not None, "B-2 拆分失败：未找到 进入-中枢-离开 结构"
    zs_span, enter, leave = result
    print(f"拆分: 进入腿 bi{enter[0]}-{enter[-1]} | 中枢 span bi{zs_span[0]}-{zs_span[-1]}"
          f" | 离开腿 bi{leave[0]}-{leave[-1]}")

    zs_seg = zs_from_span(zs_span, bi, case.bars)
    zs_leave = zs_from_span(leave, bi, case.bars)
    print(f"段内中枢:      {zs_seg}")
    print(f"离开腿次级别:  {zs_leave}\n")

    hist = calc_macd([float(b.c) for b in case.bars])[2]
    a_enter_s = _span_area_sigma(enter, bi, case.bars)
    a_leave_s = _span_area_sigma(leave, bi, case.bars)
    a_enter_m = _span_area_macd(enter, bi, hist)
    a_leave_m = _span_area_macd(leave, bi, hist)
    dir_pos = [k for k in leave if bi[k].dir is seg.dir]
    a_first_s = _bi_area_sigma(bi[dir_pos[0]], case.bars)
    a_last_s = _bi_area_sigma(bi[dir_pos[-1]], case.bars)
    a_first_m = _bi_area_macd(bi[dir_pos[0]], hist)
    a_last_m = _bi_area_macd(bi[dir_pos[-1]], hist)
    bsp_idx = bi[leave[-1]].end_idx

    print("面积（σ |Δc| / MACD |hist| 双口径）：")
    print(f"  进入腿 {a_enter_s:.2f} / {a_enter_m:.4f}  vs  离开腿 {a_leave_s:.2f} / {a_leave_m:.4f}"
          f"  → 段级背驰: σ={a_leave_s < a_enter_s} macd={a_leave_m < a_enter_m}")
    print(f"  离开腿首笔 {a_first_s:.2f} / {a_first_m:.4f}  vs  末笔 {a_last_s:.2f} / {a_last_m:.4f}"
          f"  → 次级别背驰: σ={a_last_s < a_first_s} macd={a_last_m < a_first_m}")
    print(f"  买点落点: @{bsp_idx}\n")

    ez = case.expect["zs"]
    eb = case.expect["bsp"]
    checks = [
        ("中枢区间", zs_seg["zd"] == ez[0]["zd"] and zs_seg["zg"] == ez[0]["zg"]),
        ("中枢端点", zs_seg["start"] == ez[0]["start_idx"] and zs_seg["end"] == ez[0]["end_idx"]),
        ("次级别中枢区间", zs_leave["zd"] == ez[1]["zd"] and zs_leave["zg"] == ez[1]["zg"]),
        ("次级别中枢端点", zs_leave["start"] == ez[1]["start_idx"] and zs_leave["end"] == ez[1]["end_idx"]),
        ("段级一买@46", a_leave_s < a_enter_s and a_leave_m < a_enter_m and bsp_idx == 46),
        ("次级别一买@46", a_last_s < a_first_s and a_last_m < a_first_m),
        ("买点方向=买(up)", seg.dir is Direction.DOWN),
    ]
    for name, ok in checks:
        print(f"  {'✓' if ok else '✗'} {name}")
    print(f"\n结论: {'B-2 原型在 BC-002 上重构成功' if all(ok for _, ok in checks) else 'B-2 原型未通过'}")
    print(f"  （expect bsp 锚: {[(b['idx'], b['bstype'], b['dir'], b['level']) for b in eb]}）")


if __name__ == "__main__":
    main()
