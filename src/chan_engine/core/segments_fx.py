"""M7-6 G5: 特征序列线段构造器（课 65/67/71/78，ADR-003 口径 A、ADR-004、ADR-012 方案 C）。

seg 表 = 特征序列严格口径（教科书线段，对外报告/消费）；递归层内部走势单元
保留 greedy-3bi（core/segments.py，课 35/84 f1(a0) 递归构造物）——双轨制，
本模块不替换 greedy，只接管对外 seg 表（ADR-012 方案 C，B 演进后置）。

算法（课 67/71 第一性原理，chanpy Seg/EigenFX 语义参照）：

1. **特征序列** = 线段反向笔序列（向上线段考察向下笔序列，反之亦然，课 67）。
2. **包含处理**只对同一序列相邻元素（课 71）：末元素包含新笔 → 吸收合并
   （向上线段取 max/max，向下线段取 min/min——合并方向同线段方向，同
   chanpy ``CEigenFX.kl_dir``）；末元素被新笔包含 → 不合并、新开元素
   （excluded）；无包含 → 新开元素。吸收不触发分型复判（窗口未推进）。
3. **分型判定**（最近三元素窗口，新元素入列时判定）：向上线段只考察顶分型
   （中元素高、低点均最高），向下线段只考察底分型（均最低）。
4. **缺口**（合并后元素间，ADR-003 口径 A）：顶分型 e1.high < e2.low；
   底分型 e1.low > e2.high。
5. **情况 1（无缺口）** → 段终结于中元素极值笔边界（end_bi = 极值笔序号 - 1），
   新段自极值笔起。
6. **情况 2（有缺口）** → 候选转折点，进入课 71 观察：自转折点后逐笔，
   反向笔先破第一笔（转折点处首根反向笔）结束位 → 确认（新段成立）；
   原方向笔先破第一笔开始位（转折点极值）→ 古怪（课 78/ADR-004）取消候选、
   原段延续（观察期扣留的反向笔重放入特征序列——课 71"中间地带笔"在
   候选取消后回归原序列）；数据末尾未确认 → 段收于候选点 sure=False。
7. **sure 透传**：段内任一末位笔 sure=False → 段 sure=False；未被破坏的
   末段（含候选悬置段）→ sure=False（右侧确认纪律，与五表一致）。
8. **课 78 标准化**：段端点非极值时区间取实际极值包络——SegType.high/low
   由全段笔包络计算，天然满足（SEG-005 锚）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chan_engine.core.model import SegType
from chan_engine.core.segments import _bi_high_low
from chan_engine.spec.model import Bar, Bi, Direction

SOURCE = "recursion"


@dataclass
class _Elem:
    """特征序列元素（可能为合并多笔的运行体）。"""

    bis: list[int] = field(default_factory=list)  # 构成笔的序号（时间序）
    high: float = 0.0
    low: float = 0.0


@dataclass
class _Pending:
    """情况 2 候选：缺口分型后的课 71 观察状态。"""

    end_bi: int  # 候选分界：段若终结则收于此（= 极值笔序号 - 1）
    turn: float  # 转折点极值（第一笔开始位；向上线段=高点，向下=低点）
    r1_end: float  # 第一笔（转折点处首根反向笔）结束位极值


def _feed(elems: list[_Elem], bi_idx: int, bi: Bi, bars: list[Bar],
          seg_dir: Direction) -> bool:
    """反向笔喂入特征序列（课 71 包含处理）。返回是否新开了元素。

    合并方向同线段方向：向上线段 max/max，向下线段 min/min（chanpy 同口径）。
    吸收（未新开元素）返回 False——窗口未推进，不触发分型复判。
    """
    lo, hi = _bi_high_low(bi, bars)
    if elems:
        last = elems[-1]
        if last.low <= lo and last.high >= hi:
            # 末元素包含新笔 → 吸收
            if seg_dir is Direction.UP:
                last.high = max(last.high, hi)
                last.low = max(last.low, lo)
            else:
                last.high = min(last.high, hi)
                last.low = min(last.low, lo)
            last.bis.append(bi_idx)
            return False
        # 末元素被新笔包含（excluded）与无包含，均新开元素
    elems.append(_Elem(bis=[bi_idx], high=hi, low=lo))
    return True


def _is_fractal(e1: _Elem, e2: _Elem, e3: _Elem, seg_dir: Direction) -> bool:
    """三元素窗口分型判定：向上线段看顶分型（中元素高低点均最高），反之底分型。"""
    if seg_dir is Direction.UP:
        return (e2.high > e1.high and e2.high > e3.high
                and e2.low > e1.low and e2.low > e3.low)
    return (e2.high < e1.high and e2.high < e3.high
            and e2.low < e1.low and e2.low < e3.low)


def _has_gap(e1: _Elem, e2: _Elem, seg_dir: Direction) -> bool:
    """缺口（ADR-003 口径 A）：顶分型 e1.high < e2.low；底分型 e1.low > e2.high。"""
    if seg_dir is Direction.UP:
        return e1.high < e2.low
    return e1.low > e2.high


def _peak_bi(elem: _Elem, bi_list: list[Bi], bars: list[Bar],
             seg_dir: Direction) -> int:
    """中元素内的极值笔序号（合并元素取最新达成极值者，chanpy get_peak_klu 同口径）。

    向上线段特征序列（向下笔）的顶 = 元素内 high 最大的笔（其起点即段最高点）；
    向下线段取 low 最小的笔。
    """
    target = elem.high if seg_dir is Direction.UP else elem.low
    for idx in reversed(elem.bis):
        lo, hi = _bi_high_low(bi_list[idx], bars)
        if (hi if seg_dir is Direction.UP else lo) == target:
            return idx
    raise AssertionError("peak bi not found in element")  # pragma: no cover


def _breaks_turn(bi: Bi, bars: list[Bar], turn: float, seg_dir: Direction) -> bool:
    """原方向笔是否破第一笔开始位（转折点极值）→ 古怪取消（课 78）。"""
    end_bar = bars[bi.end_idx]
    if seg_dir is Direction.UP:
        return end_bar.h > turn
    return end_bar.l < turn


def _breaks_r1_end(bi: Bi, bars: list[Bar], r1_end: float,
                   seg_dir: Direction) -> bool:
    """反向笔是否破第一笔结束位 → 情况 2 确认（claim-20070816-001-b）。"""
    end_bar = bars[bi.end_idx]
    if seg_dir is Direction.UP:
        return end_bar.l < r1_end
    return end_bar.h > r1_end


def build_fx_segments(bi_list: list[Bi], bars: list[Bar]) -> list[SegType]:
    """从归一笔表构造特征序列口径线段（课 67/71/78 完整两情况 + 缺口）。

    参数：
        bi_list: 归一笔表（``spec.model.Bi``，含方向与端点 bar 下标）。
        bars:    原始 K 线（计算笔/元素极值）。

    返回：
        按时间顺序的 SegType 列表；不足 3 笔的尾笔不成段（课 69）。
    """
    n = len(bi_list)
    if n < 3:
        return []

    segs: list[SegType] = []
    seg_start = 0
    seg_dir = bi_list[0].dir
    elems: list[_Elem] = []
    pending: _Pending | None = None
    held: list[int] = []  # 候选观察期扣留的反向笔序号（课 71 中间地带笔）

    def emit(end_bi: int, sure: bool) -> None:
        span = bi_list[seg_start : end_bi + 1]
        highs: list[float] = []
        lows: list[float] = []
        for b in span:
            lo, hi = _bi_high_low(b, bars)
            lows.append(lo)
            highs.append(hi)
        segs.append(SegType(
            start_bi=seg_start,
            end_bi=end_bi,
            dir=seg_dir,
            high=max(highs),
            low=min(lows),
            sure=sure and all(b.sure for b in span),
            source=SOURCE,
        ))

    i = 1
    while i < n:
        bi = bi_list[i]
        if pending is not None:
            if bi.dir is seg_dir:
                if _breaks_turn(bi, bars, pending.turn, seg_dir):
                    # 古怪取消（课 78）：原段延续，扣留笔回卷重放
                    pending = None
                    i = held[0] if held else i + 1
                    held = []
                else:
                    i += 1
                continue
            if _breaks_r1_end(bi, bars, pending.r1_end, seg_dir):
                # 情况 2 确认：段收于候选点，新段自极值笔起重扫
                emit(pending.end_bi, sure=True)
                seg_start = pending.end_bi + 1
                seg_dir = bi_list[seg_start].dir
                elems = []
                pending = None
                held = []
                i = seg_start + 1
            else:
                held.append(i)
                i += 1
            continue

        if bi.dir is seg_dir:
            i += 1
            continue

        appended = _feed(elems, i, bi, bars, seg_dir)
        i += 1
        if not appended or len(elems) < 3:
            continue
        e1, e2, e3 = elems[-3], elems[-2], elems[-1]
        if not _is_fractal(e1, e2, e3, seg_dir):
            continue
        peak = _peak_bi(e2, bi_list, bars, seg_dir)
        if peak - 1 < seg_start + 2:
            continue  # 段至少 3 笔（课 69）：分型中元素过早，不构成有效分界
        if not _has_gap(e1, e2, seg_dir):
            # 情况 1：无缺口，分型成立即终结
            emit(peak - 1, sure=True)
            seg_start = peak
            seg_dir = bi_list[seg_start].dir
            elems = []
            held = []
            i = seg_start + 1
            continue
        # 情况 2：候选，课 71 观察（含既有笔的即时扫描——第三元素可能已破位）
        r1 = bi_list[peak]
        r1_lo, r1_hi = _bi_high_low(r1, bars)
        cand = _Pending(
            end_bi=peak - 1,
            turn=e2.high if seg_dir is Direction.UP else e2.low,
            r1_end=r1_lo if seg_dir is Direction.UP else r1_hi,
        )
        decided = False
        for j in range(peak + 1, i):
            bj = bi_list[j]
            if bj.dir is seg_dir:
                if _breaks_turn(bj, bars, cand.turn, seg_dir):
                    decided = True  # 古怪取消（候选形成前已创极值）
                    break
            elif _breaks_r1_end(bj, bars, cand.r1_end, seg_dir):
                decided = True
                emit(cand.end_bi, sure=True)  # 即时确认（SEG-003 路径）
                seg_start = peak
                seg_dir = bi_list[seg_start].dir
                elems = []
                held = []
                i = seg_start + 1
                break
        if decided:
            continue
        pending = cand  # 未决 → 悬置，后续笔进入观察
        held = []

    # 末段（尾巴）：未被破坏 → sure=False（右侧确认纪律）
    if pending is not None:
        # 候选悬置：段收于候选点；候选点后余笔够 3 笔另起未决段
        emit(pending.end_bi, sure=False)
        tail_start = pending.end_bi + 1
        if n - tail_start >= 3:
            span = bi_list[tail_start:]
            highs, lows = [], []
            for b in span:
                lo, hi = _bi_high_low(b, bars)
                lows.append(lo)
                highs.append(hi)
            segs.append(SegType(
                start_bi=tail_start,
                end_bi=n - 1,
                dir=bi_list[tail_start].dir,
                high=max(highs),
                low=min(lows),
                sure=False,
                source=SOURCE,
            ))
    elif n - seg_start >= 3:
        emit(n - 1, sure=False)
    return segs
