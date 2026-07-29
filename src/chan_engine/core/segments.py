"""M3-1: L0 走势类型（线段）自建分组。

递归层不消费适配器的 seg 表——chanpy 对 BC-002 把九笔并成一段
（seg=[(0,8,down)]），破坏了 A2/B2/C2 三段结构；czsc 干脆不产出 seg
（na_fields 含 "seg"）。因此从归一 bi 表 + bars 自行分组。

分组规则（以 expect 语料校准，逆向自 BC-002/SEG-001/002/003）：

1. **最小段 = 3 笔**：贪婪取 bi[i..i+2]，段方向 = 首笔方向（课 69：线段至少三笔）。
2. **同向扩展**：段方向上的同向笔（与首笔同向）若创出**新极值**
   （下跌段末笔低点更低 / 上涨段末笔高点更高），则把随后的反向笔与该同向笔
   一并吸收进段；否则段结束于当前最后一根同向笔。
3. **残笔不成段**：末尾不足 3 笔的余笔（如 BC-002 的 bi9）不成段。
4. **sure 透传**：段内任一末位笔 sure=False（未右侧确认）→ 段 sure=False。

该规则与 chanpy"破前摆极值才反向"的口径不同（故 chanpy 九并一），是递归层
自建分组的根本动机；与 SEG-001~003 的特征序列口径在同批语料上结果一致
（已逐案核对），差异点登记 ADR。
"""

from __future__ import annotations

from chan_engine.core.model import SegType
from chan_engine.spec.model import Bar, Bi, Direction

MIN_BI_PER_SEGMENT = 3


def _bi_high_low(bi: Bi, bars: list[Bar]) -> tuple[float, float]:
    """单笔的 (low, high) 极值包络：取两端点分型的极值。

    向上笔：low=起点 bar 最低价，high=终点 bar 最高价；
    向下笔：low=终点 bar 最低价，high=起点 bar 最高价。
    （与 M2 归一 zs 构造的笔区间口径一致。）
    """
    start_bar = bars[bi.start_idx]
    end_bar = bars[bi.end_idx]
    if bi.dir is Direction.UP:
        return start_bar.l, end_bar.h
    return end_bar.l, start_bar.h


def _directional_extreme(bi: Bi, bars: list[Bar]) -> float:
    """笔在其运动方向上的极值（终点极值）：向上笔=终点高，向下笔=终点低。"""
    end_bar = bars[bi.end_idx]
    return end_bar.h if bi.dir is Direction.UP else end_bar.l


def _makes_new_extreme(prev: float, nxt: float, seg_dir: Direction) -> bool:
    """下一同向笔是否相对前一同向笔创出段方向新极值。"""
    if seg_dir is Direction.UP:
        return nxt > prev
    return nxt < prev


def build_l0_segments(bi_list: list[Bi], bars: list[Bar]) -> list[SegType]:
    """从归一笔表分组 L0 走势类型（线段）。

    参数：
        bi_list: 归一笔表（``spec.model.Bi``，含方向与端点 bar 下标）。
        bars:    原始 K 线（计算笔/段极值）。

    返回：
        按时间顺序的 SegType 列表；不足最小段的残笔被丢弃。
    """
    n = len(bi_list)
    segments: list[SegType] = []
    i = 0
    while i + MIN_BI_PER_SEGMENT - 1 < n:
        seg_dir = bi_list[i].dir
        # 最小 3 笔段：i(同向) i+1(反向) i+2(同向)，末一根同向笔 = i+2
        last_dir_bi = i + 2
        # 同向扩展：下一同向笔 = last_dir_bi + 2，须创出段方向新极值
        while last_dir_bi + 2 < n and bi_list[last_dir_bi + 2].dir is seg_dir:
            prev_ext = _directional_extreme(bi_list[last_dir_bi], bars)
            next_ext = _directional_extreme(bi_list[last_dir_bi + 2], bars)
            if _makes_new_extreme(prev_ext, next_ext, seg_dir):
                last_dir_bi += 2
            else:
                break
        end = last_dir_bi
        segments.append(_make_segment(bi_list, bars, i, end, seg_dir))
        i = end + 1
    return segments


def _make_segment(
    bi_list: list[Bi], bars: list[Bar], start: int, end: int, seg_dir: Direction
) -> SegType:
    """构造单个 SegType：极值包络 + sure 透传。"""
    span = bi_list[start : end + 1]
    highs: list[float] = []
    lows: list[float] = []
    for bi in span:
        lo, hi = _bi_high_low(bi, bars)
        lows.append(lo)
        highs.append(hi)
    sure = all(bi.sure for bi in span)
    return SegType(
        start_bi=start,
        end_bi=end,
        dir=seg_dir,
        high=max(highs),
        low=min(lows),
        sure=sure,
        source="recursion",
    )
