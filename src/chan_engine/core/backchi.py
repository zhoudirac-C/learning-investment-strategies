"""M3-3: 背驰判断 + 多级买卖点生成。

背驰口径（BC-002 expect + 课 27 精确大转折点寻找程序定理实证）：

- **面积代理** = 段内全部笔 |收盘变化| 之和（``Σ|Δc|``，Δc = 笔终点收盘 − 笔起点收盘）。
- **level-N+1 背驰**：进入段面积 vs 离开段面积（同向比较），``离开 < 进入`` →
  大级别背驰 → 在离开段终点出 一买/一卖（level=N+1）。
  BC-002：A2=10.84 > C2=6.04 → level-2 一买@46。
- **level-N 背驰**：离开段内 首同向笔 vs 末同向笔（``a1`` vs ``c1``），``末 < 首`` →
  次级别背驰 → 同一点再出 一买/一卖（level=N）。
  BC-002：a1=2.88 > c1=2.08 → level-1 一买@46。
- **买卖点方向**：下跌走势（离开段向下）背驰 → 一买 ``dir=up``；
  上涨走势（离开段向上）背驰 → 一卖 ``dir=down``。
- sure：形成即确认（附录 C.1 zs/bsp 约定）。

只产出背驰触发的第一/二类买卖点雏形；第三类买卖点（回试不破 ZG/ZD）属
走势类型判定（BSP-003），在 engine 集成层另行处理。
"""

from __future__ import annotations

from chan_engine.core.model import SegType
from chan_engine.spec.model import Bar, Bi, BSPoint, Direction

SOURCE = "recursion"


def _bi_area(bi: Bi, bars: list[Bar]) -> float:
    """单笔面积代理：|笔终点收盘 − 笔起点收盘|。"""
    return abs(float(bars[bi.end_idx].c) - float(bars[bi.start_idx].c))


def _segment_area(seg: SegType, bi_list: list[Bi], bars: list[Bar]) -> float:
    """段面积 = 段内全部笔面积之和。"""
    return sum(_bi_area(bi_list[k], bars) for k in range(seg.start_bi, seg.end_bi + 1))


def _segment_internal_backchi(seg: SegType, bi_list: list[Bi], bars: list[Bar]) -> bool:
    """段内背驰：首同向笔面积 > 末同向笔面积（a1 vs c1）。

    段方向上的同向笔 = 与 seg.dir 同向的笔（首笔、第三笔、…）。
    """
    directional = [
        bi_list[k]
        for k in range(seg.start_bi, seg.end_bi + 1)
        if bi_list[k].dir is seg.dir
    ]
    if len(directional) < 2:
        return False
    first_area = _bi_area(directional[0], bars)
    last_area = _bi_area(directional[-1], bars)
    return last_area < first_area


def _bsp_dir_for(seg_dir: Direction) -> Direction:
    """离开段方向 → 买卖点方向：下跌背驰→一买(up)，上涨背驰→一卖(down)。"""
    return Direction.UP if seg_dir is Direction.DOWN else Direction.DOWN


def detect_backchi_bsp(
    segments: list[SegType], bi_list: list[Bi], bars: list[Bar]
) -> list[BSPoint]:
    """对 进入+中枢+离开 三件套做背驰判断，产出多级买卖点。

    扫描方向模式 X,~X,X 的三段；对每组：
    - level-2 背驰（进入段 vs 离开段面积）→ level=2 买卖点；
    - level-1 背驰（离开段内首末同向笔）→ level=1 买卖点；
    两点同落在离开段末笔终点。
    """
    bsp_out: list[BSPoint] = []
    i = 0
    while i + 2 < len(segments):
        s0, s1, s2 = segments[i], segments[i + 1], segments[i + 2]
        if s0.dir is s2.dir and s1.dir is not s0.dir:
            end_bar_idx = bi_list[s2.end_bi].end_idx
            bdir = _bsp_dir_for(s2.dir)
            # level-2 背驰：进入段 vs 离开段
            if _segment_area(s2, bi_list, bars) < _segment_area(s0, bi_list, bars):
                bsp_out.append(
                    BSPoint(idx=end_bar_idx, bstype=1, dir=bdir, level=2, sure=True, source=SOURCE)
                )
            # level-1 背驰：离开段内 a1 vs c1
            if _segment_internal_backchi(s2, bi_list, bars):
                bsp_out.append(
                    BSPoint(idx=end_bar_idx, bstype=1, dir=bdir, level=1, sure=True, source=SOURCE)
                )
            i += 3
        else:
            i += 1
    return bsp_out
