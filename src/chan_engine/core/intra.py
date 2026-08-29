"""M7-7 T1: fx 段内笔级重释（B-2 路线，ADR-012 B 演进）。

递归层内部走势单元 = 课 67/71/78 特征序列线段（core/segments_fx.py），段不拆；
段内按笔级"同向笔创/未创段方向新极值"分推动笔/修正笔，修正笔 run 夹出中枢
span（课 17 首三笔严格重叠 + 已确认笔延伸，与 levels._segment_zhongshu 同口径），
在段内重构 进入-中枢-离开 结构。

产出契约（全量语料影子验证，`logs/chan-b2-shadow-20260829.md`，31 用例 21/10
与 greedy 基线逐格零变化）：

- **单中枢 + 进入腿 ≥3 笔 → 盘整**：中枢标 level=2（契约保留），离开腿内首三笔
  中枢 level=1；背驰双级别（MACD 主口径）：进入腿 vs 离开腿 → level=2 买卖点，
  离开腿内首末同向笔 → level=1。BC-002 锚：[23.9,26.2]@16→31 + [22.9,24.4]@31→46
  + 双一买@46。
- **单中枢 + 进入腿 <3 笔**，或修正结构缺反向笔确认（尾部悬置）→ **Path B**：
  段首三笔（含引导笔）重叠 → level=1。BSP-003 锚：[11.4,14.0]@1→16。
- **≥2 中枢 → 趋势**：各中枢 level=1；趋势背驰 = 末离开腿 vs 前一连接腿面积
  → level=1 买卖点。BC-001 锚：[26.3,29.3]@6→21 + [22.7,24.8]@26→41。
- 纯推动段（同向笔连创新极值、无修正）→ 无产出。ZS-001 锚。

sure 纪律：尾部未确认笔剔除出结构；中枢种子笔全 sure 才 sure；买卖点 sure 透传
离开腿。背驰标注 backchi_type（core.backchi.classify_backchi_type，G3 前提校验）。
"""

from __future__ import annotations

from chan_engine.core.backchi import classify_backchi_type
from chan_engine.core.model import SegType
from chan_engine.core.segments import _bi_high_low
from chan_engine.spec.model import Bar, Bi, BSPoint, Direction, ZhongShu

SOURCE = "recursion"

#: 盘整/趋势的进入腿最小笔数（次级别走势类型至少三笔，课 69 精神）
MIN_LEG_BI = 3


def decompose_segment(
    seg: SegType, bi_list: list[Bi], bars: list[Bar]
) -> tuple[list[int], list[list[int]], list[list[int]], bool]:
    """fx 段内拆分 → (pos, 中枢 span 列表, 腿列表, 是否出现修正结构)。

    - pos：段内参与分析的笔位置（尾部未确认笔剔除，greedy"残笔不成段"同纪律）；
    - 同向笔（与 seg.dir 同向）分类：创段方向新极值 → 推动笔，否则 → 修正笔；
    - 修正笔连续 run → 中枢 span = run 首笔前的反向笔 .. run 末笔后的反向笔；
      缺任一侧反向笔 → 尾部悬置，该 run 及其后结构不定型（不成中枢）；
    - legs：中枢 span 之间/两端的笔位置（legs[0]=进入腿，legs[-1]=末离开腿）。
    """
    pos = list(range(seg.start_bi, seg.end_bi + 1))
    while pos and not bi_list[pos[-1]].sure:
        pos.pop()
    if len(pos) < MIN_LEG_BI:
        return pos, [], [], False
    running: float | None = None
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
            break  # 中枢缺反向笔确认 → 尾部悬置
        spans.append(list(range(a, b + 1)))
    legs: list[list[int]] = []
    prev = pos[0]
    for span in spans:
        legs.append([k for k in pos if prev <= k < span[0]])
        prev = span[-1] + 1
    legs.append([k for k in pos if k >= prev])
    return pos, spans, legs, had_corrective


def span_zhongshu(
    span: list[int], bi_list: list[Bi], bars: list[Bar], level: int
) -> ZhongShu | None:
    """span 首三笔严格重叠中枢（课 17：ZD=max(三笔低点)，ZG=min(三笔高点)）。

    后续**已确认**笔严格重叠则延伸 end（zd/zg 不随延伸更新，对齐 chanpy
    try_add_to_end 与 czsc M2-3 口径，同 levels._segment_zhongshu）。
    """
    if len(span) < MIN_LEG_BI:
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
    return ZhongShu(
        zd=zd,
        zg=zg,
        start_idx=bi_list[seed[0]].start_idx,
        end_idx=end_idx,
        level=level,
        sure=all(bi_list[k].sure for k in seed),
        source=SOURCE,
    )


def _leg_area_macd(leg: list[int], bi_list: list[Bi], hist: list[float]) -> float:
    """腿面积（MACD 主口径）：腿首笔起点 bar ~ 末笔终点 bar 的 |hist| 和。"""
    start = bi_list[leg[0]].start_idx
    end = bi_list[leg[-1]].end_idx
    return sum(abs(hist[i]) for i in range(start, end + 1))


def _bi_area_macd(bi: Bi, hist: list[float]) -> float:
    """单笔面积（MACD 主口径）：笔端点 bar 闭区间 |hist| 求和。"""
    return sum(abs(hist[i]) for i in range(bi.start_idx, bi.end_idx + 1))


def emit_intra_zs_bsp(
    seg: SegType,
    bi_list: list[Bi],
    bars: list[Bar],
    hist: list[float],
    zs_context: list[ZhongShu],
) -> tuple[list[ZhongShu], list[BSPoint]]:
    """单个 fx 段的段内重释 → (中枢列表, 背驰买卖点列表)。

    ``zs_context``：本段之前已产出的中枢（M-a 三件套 + 先前段），供
    backchi_type 前提校验（同级别、同向不重叠前中枢 → trend_div，否则
    consolidation_div）。
    """
    pos, spans, legs, had_corrective = decompose_segment(seg, bi_list, bars)
    bdir = Direction.UP if seg.dir is Direction.DOWN else Direction.DOWN

    if not spans:
        # Path B：修正结构存在但中枢未确认（尾部悬置/段首即修正）→ 段首三笔
        if had_corrective and len(pos) >= MIN_LEG_BI:
            z = span_zhongshu(pos[:3], bi_list, bars, level=1)
            return ([z] if z is not None else []), []
        return [], []

    zss = [span_zhongshu(s, bi_list, bars, 1) for s in spans]
    if zss[0] is None:
        return [], []  # 首个修正结构无重叠 → 非中枢，全段保守无产出

    if len(spans) == 1 and len(legs[0]) < MIN_LEG_BI:
        # Path B：进入腿过短（段首即中枢）→ 段首三笔（含引导笔）
        z = span_zhongshu(pos[:3], bi_list, bars, level=1)
        return ([z] if z is not None else []), []

    if len(spans) == 1:
        # 盘整：中枢 L2 + 离开腿内 L1 + 双级别背驰
        core = span_zhongshu(spans[0], bi_list, bars, level=2)
        zs_out = [core] if core is not None else []
        enter, leave = legs[0], legs[1]
        bsp_out: list[BSPoint] = []
        if not leave:
            return zs_out, bsp_out
        z1 = span_zhongshu(leave, bi_list, bars, level=1)
        if z1 is not None:
            zs_out.append(z1)
        backchi_type = classify_backchi_type(
            zs_context + zs_out, core, seg.dir
        ) if core is not None else "consolidation_div"
        sure = all(bi_list[k].sure for k in leave)
        idx = bi_list[leave[-1]].end_idx
        if _leg_area_macd(leave, bi_list, hist) < _leg_area_macd(enter, bi_list, hist):
            bsp_out.append(BSPoint(idx=idx, bstype=1, dir=bdir, level=2, sure=sure,
                                   source=SOURCE, backchi_type=backchi_type))
        dir_bi = [k for k in leave if bi_list[k].dir is seg.dir]
        if len(dir_bi) >= 2 and _bi_area_macd(bi_list[dir_bi[-1]], hist) < _bi_area_macd(
            bi_list[dir_bi[0]], hist
        ):
            bsp_out.append(BSPoint(idx=idx, bstype=1, dir=bdir, level=1, sure=sure,
                                   source=SOURCE, backchi_type=backchi_type))
        return zs_out, bsp_out

    # 趋势（≥2 中枢）：各 L1 + 趋势背驰（连接腿 vs 末离开腿）
    zs_out = [z for z in zss if z is not None]
    bsp_out = []
    leave, connector = legs[-1], legs[-2]
    core = zs_out[-1]
    backchi_type = classify_backchi_type(zs_context + zs_out, core, seg.dir)
    if (
        leave
        and connector
        and _leg_area_macd(leave, bi_list, hist) < _leg_area_macd(connector, bi_list, hist)
    ):
        bsp_out.append(BSPoint(idx=bi_list[leave[-1]].end_idx, bstype=1, dir=bdir,
                               level=1, sure=all(bi_list[k].sure for k in leave),
                               source=SOURCE, backchi_type=backchi_type))
    return zs_out, bsp_out
