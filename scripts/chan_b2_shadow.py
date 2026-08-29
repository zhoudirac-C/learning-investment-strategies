#!/usr/bin/env python
"""B-2 全量影子引擎验证：fx 段 + 段内笔级重释，对照全量 31 语料的 expect。

在 B-3 证据（logs/chan-fx-shadow-20260829.md：直接换内部单元 → 2 回归 0 修复）
之上验证 ADR-012 方案 B 的可行路线——**不拆 fx 段，段内按笔级"创/未创段方向
新极值"重构 进入-中枢-离开 结构**（scripts/chan_b2_prototype_bc002.py 的泛化）。

管线（与 core.engine._compose 对齐，仅内部走势单元语义不同）：
- fx/bi 表：chanpy 适配器委托（与现状一致）；seg 表：build_fx_segments（现状一致）；
- M-a 段间三件套：find_trend_patterns(fx 段) → 中枢段内中枢 L2 / 离开段内中枢 L1
  （复用 core.levels.synthesize_level_zs 口径）；
- M-b 段内重释（仅作用于未被 M-a 消费的 fx 段）：
  * 段内同向笔分 推动笔（创段方向新极值）/ 修正笔；修正笔连续 run 夹出中枢 span
    （run 首笔前的反向笔 .. run 末笔后的反向笔），课 17 首三笔严格重叠 + 已确认笔延伸；
  * 单中枢 + 进入腿 ≥3 笔 → 盘整（Path A）：中枢 L2 + 离开腿内中枢 L1 +
    双级别背驰买卖点（MACD 主口径，进入腿 vs 离开腿 / 离开腿内首末同向笔）；
  * 单中枢 + 进入腿 <3 笔 → Path B：段首三笔重叠 → L1（BSP-003 口径）；
  * ≥2 中枢 → 趋势：各中枢 L1 + 趋势背驰一买/一卖（连接腿 vs 末离开腿，L1）；
- 九段升级（笔级，core.levels.apply_nine_bi_upgrade）、二买二卖、三买三卖、
  GOLD 箱体兜底：与现状一致。

用法（仓根）：
    PYTHONPATH=src:third_party/chanpy .venv/bin/python scripts/chan_b2_shadow.py
"""

from __future__ import annotations

import dataclasses
import glob
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "third_party" / "chanpy"))

from chan_engine.core.backchi import (
    detect_backchi_bsp,
    detect_second_type_bsp,
    detect_third_type_bsp,
)
from chan_engine.core.fxlevel import detect_box_third_buy
from chan_engine.core.levels import (
    apply_nine_bi_upgrade,
    find_trend_patterns,
    synthesize_level_zs,
)
from chan_engine.core.macd import calc_macd
from chan_engine.core.segments import _bi_high_low
from chan_engine.core.segments_fx import build_fx_segments
from chan_engine.core.trend import analyze_trend
from chan_engine.harness.adapter_chanpy import ChanPyAdapter
from chan_engine.harness.diff import diff_expect
from chan_engine.spec.case_io import load_case
from chan_engine.spec.model import Bar, Bi, BSPoint, Direction, Segment, ZhongShu

SOURCE = "recursion"
CASES_DIR = REPO / "src/chan_engine/spec/cases"
GOLDEN_DIR = REPO / "src/chan_engine/spec/golden"


# ── M-b：fx 段内笔级重释 ──

def _span_zs(span: list[int], bi_list: list[Bi], bars: list[Bar],
             level: int) -> ZhongShu | None:
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
    return ZhongShu(zd=zd, zg=zg, start_idx=bi_list[seed[0]].start_idx,
                    end_idx=end_idx, level=level,
                    sure=all(bi_list[k].sure for k in seed), source=SOURCE)


def _decompose(seg, bi_list, bars):
    """fx 段内拆分 → (pos, consolidations, legs)。

    consolidations[i] = 中枢 span（bi 位置列表）；legs[j] = 中枢间/两端的腿。
    尾部未确认笔剔除；无后续反向笔确认的修正 run 不成中枢（尾部悬置）。
    """
    pos = list(range(seg.start_bi, seg.end_bi + 1))
    while pos and not bi_list[pos[-1]].sure:
        pos.pop()
    if len(pos) < 3:
        return pos, [], [], False
    running = None
    runs: list[list[int]] = []
    for k in [k for k in pos if bi_list[k].dir is seg.dir]:
        bar = bars[bi_list[k].end_idx]
        cur = bar.l if seg.dir is Direction.DOWN else bar.h
        if running is None:
            running = cur
            runs.append([])
            continue
        new_extreme = cur < running if seg.dir is Direction.DOWN else cur > running
        if new_extreme:
            running = cur
            runs.append([])
        else:
            runs[-1].append(k)
    had_corrective = any(runs)
    spans: list[list[int]] = []
    for run in runs:
        if not run:
            continue
        a, b = run[0] - 1, run[-1] + 1
        if a < pos[0] or b > pos[-1]:
            break  # 中枢缺反向笔确认 → 尾部悬置，后续结构不定型
        spans.append(list(range(a, b + 1)))
    legs: list[list[int]] = []
    prev = pos[0]
    for span in spans:
        legs.append([k for k in pos if prev <= k < span[0]])
        prev = span[-1] + 1
    legs.append([k for k in pos if k >= prev])
    return pos, spans, legs, had_corrective


def _leg_area(leg: list[int], bi_list: list[Bi], hist: list[float]) -> float:
    """腿面积（MACD 主口径）：腿首笔起点 ~ 末笔终点 |hist| 和。"""
    start = bi_list[leg[0]].start_idx
    end = bi_list[leg[-1]].end_idx
    return sum(abs(hist[i]) for i in range(start, end + 1))


def _emit_intra(seg, bi_list, bars, hist):
    """单个 fx 段的段内重释 → (zs, bsp)。"""
    pos, spans, legs, had_corrective = _decompose(seg, bi_list, bars)
    if not spans:
        # 修正结构存在但中枢缺反向笔确认（尾部悬置/段首即修正）→ Path B 首三笔
        if had_corrective and len(pos) >= 3:
            z = _span_zs(pos[:3], bi_list, bars, 1)
            return ([z] if z is not None else []), []
        return [], []
    zss = [_span_zs(s, bi_list, bars, 1) for s in spans]
    if zss[0] is None:
        return [], []  # 首个"修正结构"无重叠 → 非中枢，全段无产出（保守）
    bdir = Direction.UP if seg.dir is Direction.DOWN else Direction.DOWN

    if len(spans) == 1 and len(legs[0]) < 3:
        # Path B：段首三笔（含引导笔）→ L1（BSP-003 口径）
        z = _span_zs(pos[:3], bi_list, bars, 1)
        return ([z] if z is not None else []), []

    if len(spans) == 1:
        # Path A 盘整：中枢 L2 + 离开腿内中枢 L1 + 双级别背驰
        zs = _span_zs(spans[0], bi_list, bars, 2)
        enter, leave = legs[0], legs[1]
        zs_out = [zs] if zs is not None else []
        bsp_out: list[BSPoint] = []
        if not leave:
            return zs_out, bsp_out
        z1 = _span_zs(leave, bi_list, bars, 1)
        if z1 is not None:
            zs_out.append(z1)
        sure = all(bi_list[k].sure for k in leave)
        idx = bi_list[leave[-1]].end_idx
        if _leg_area(leave, bi_list, hist) < _leg_area(enter, bi_list, hist):
            bsp_out.append(BSPoint(idx=idx, bstype=1, dir=bdir, level=2,
                                   sure=sure, source=SOURCE))
        dir_bi = [k for k in leave if bi_list[k].dir is seg.dir]
        if len(dir_bi) >= 2:
            first = sum(abs(hist[i]) for i in range(bi_list[dir_bi[0]].start_idx,
                                                    bi_list[dir_bi[0]].end_idx + 1))
            last = sum(abs(hist[i]) for i in range(bi_list[dir_bi[-1]].start_idx,
                                                   bi_list[dir_bi[-1]].end_idx + 1))
            if last < first:
                bsp_out.append(BSPoint(idx=idx, bstype=1, dir=bdir, level=1,
                                       sure=sure, source=SOURCE))
        return zs_out, bsp_out

    # Path A 趋势（≥2 中枢）：各 L1 + 趋势背驰（连接腿 vs 末离开腿）
    zs_out = [z for z in zss if z is not None]
    bsp_out = []
    leave, connector = legs[-1], legs[-2]
    if leave and connector and _leg_area(leave, bi_list, hist) < _leg_area(connector, bi_list, hist):
        bsp_out.append(BSPoint(idx=bi_list[leave[-1]].end_idx, bstype=1, dir=bdir,
                               level=1, sure=all(bi_list[k].sure for k in leave),
                               source=SOURCE))
    return zs_out, bsp_out


# ── 影子引擎 ──

def run_b2(bars: list[Bar]) -> NormalizedChart:
    from chan_engine.spec.model import NormalizedChart

    base = ChanPyAdapter().run(bars)
    chart = NormalizedChart()
    chart.fx = [dataclasses.replace(f, source=SOURCE) for f in base.fx]
    chart.bi = [dataclasses.replace(b, source=SOURCE) for b in base.bi]
    bi_list, fx_segs = chart.bi, build_fx_segments(chart.bi, bars)
    chart.seg = [Segment(start_bi=s.start_bi, end_bi=s.end_bi, dir=s.dir,
                         sure=s.sure, source=SOURCE) for s in fx_segs]
    hist = calc_macd([float(b.c) for b in bars])[2]

    # M-a 段间三件套（fx 段级）+ M-b 段内重释（未消费段）
    consumed = {i for t in find_trend_patterns(fx_segs) for i in t}
    zs = synthesize_level_zs(fx_segs, bi_list, bars)
    bsp = detect_backchi_bsp(fx_segs, bi_list, bars)  # 只命中 M-a 三件套
    for k, seg in enumerate(fx_segs):
        if k in consumed:
            continue
        z, b = _emit_intra(seg, bi_list, bars, hist)
        zs += z
        bsp += b
    chart.zs = sorted(apply_nine_bi_upgrade(zs, bi_list, bars),
                      key=lambda z: z.start_idx)
    if chart.zs:
        top = max(z.level for z in chart.zs)
        chart.trend = analyze_trend([z for z in chart.zs if z.level == top])
    else:
        chart.trend = analyze_trend([])
    bsp += detect_second_type_bsp(bsp, bi_list, bars)
    bsp += detect_third_type_bsp(chart.zs, bi_list, bars)
    if not chart.zs and not bsp:
        bsp = detect_box_third_buy(bars)
    chart.bsp = sorted(bsp, key=lambda b: (b.idx, b.bstype, -b.level))
    return chart


def main() -> None:
    from chan_engine.core.engine import RecursionEngine

    paths = sorted(glob.glob(str(CASES_DIR / "*.yaml"))) + sorted(
        glob.glob(str(GOLDEN_DIR / "*.yaml")))
    rows = []
    for path in paths:
        case = load_case(path)
        try:
            base_d = diff_expect(case.expect, RecursionEngine().run(case.bars))
            base = "PASS" if base_d.passed else "FAIL"
        except Exception as exc:  # noqa: BLE001
            base, base_d = "ERROR", None
        try:
            b2_d = diff_expect(case.expect, run_b2(case.bars))
            b2 = "PASS" if b2_d.passed else "FAIL"
        except Exception as exc:  # noqa: BLE001
            b2, b2_d = "ERROR", None
        verdict = {"base": base, "b2": b2, "id": case.case_id}
        if base != b2:
            verdict["verdict"] = ("回归" if base == "PASS" else "修复") if "ERROR" not in (base, b2) else "错误"
            verdict["detail"] = b2_d
        else:
            verdict["verdict"] = "不变"
        rows.append(verdict)

    n_base = sum(1 for r in rows if r["base"] == "PASS")
    n_b2 = sum(1 for r in rows if r["b2"] == "PASS")
    changed = [r for r in rows if r["base"] != r["b2"]]
    print(f"基线(greedy)：{n_base} PASS / {len(rows) - n_base} FAIL"
          f"　B-2 影子：{n_b2} PASS / {len(rows) - n_b2} FAIL　判定变化 {len(changed)} 例\n")
    print("| 用例 | 基线 | B-2 | 判定 |")
    print("|---|---|---|---|")
    for r in rows:
        print(f"| {r['id']} | {r['base']} | {r['b2']} | {r['verdict']} |")
    if changed:
        print("\n## 判定变化明细\n")
        for r in changed:
            print(f"### {r['id']}：{r['base']} → {r['b2']}（{r['verdict']}）")
            d = r.get("detail")
            if d is None:
                print("- （B-2 运行错误）\n")
                continue
            for t in d.problem_tables:
                print(f"- 表 `{t.table}`：")
                for m in t.mismatches:
                    print(f"  - 字段不一致 key={m.key} {m.field}: expect={m.expected} actual={m.actual}")
                for e in t.missing:
                    print(f"  - 缺: {e}")
                for e in t.extra:
                    print(f"  - 多: {e}")
            print()


if __name__ == "__main__":
    main()
