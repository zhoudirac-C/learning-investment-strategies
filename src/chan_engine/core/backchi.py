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
from chan_engine.spec.model import Bar, Bi, BSPoint, Direction, ZhongShu

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
    from chan_engine.core.levels import find_trend_patterns

    bsp_out: list[BSPoint] = []
    for i0, _, i2 in find_trend_patterns(segments):
        s0, s2 = segments[i0], segments[i2]
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
    return bsp_out


def detect_third_type_bsp(
    zs_list: list[ZhongShu], bi_list: list[Bi], bars: list[Bar]
) -> list[BSPoint]:
    """第三类买卖点（课 20/21）：离开中枢 + 第一次回试不回到中枢。

    对每个 level-1 中枢，扫描其结束之后的已确认笔：
    - **离开**：首根突破中枢边界的笔——向上笔终点高 > ZG（三买候选）/
      向下笔终点低 < ZD（三卖候选）；笔未破界视为中枢内震荡，继续扫描；
    - **回试**：离开后的第一根反向已确认笔——三买要求回试笔低点 > ZG
      （不回到中枢），三卖要求回试笔高点 < ZD；破界回到中枢则该中枢
      三买/三卖不成立，停止扫描该中枢；
    - 买卖点落在回试笔终点，level=1，形成即确认 sure=True。

    笔级实现（M3-4）：离开/回试均以"笔"为次级别走势代理；参与笔必须
    sure=True（未确认笔直接跳过该中枢——BC-002 末位 bi9 不出三买）。
    """
    bsp_out: list[BSPoint] = []
    for zs in sorted(zs_list, key=lambda z: z.start_idx):
        if zs.level != 1:
            continue
        # 中枢结束后的笔（起点不早于中枢终点）
        later = [(k, b) for k, b in enumerate(bi_list) if b.start_idx >= zs.end_idx]
        leave_idx: int | None = None
        for k, bi in later:
            if not bi.sure:
                break  # 未确认笔 → 中枢后续结构未定，停止
            if bi.dir is Direction.UP and bars[bi.end_idx].h > zs.zg:
                leave_idx = k
                break
            if bi.dir is Direction.DOWN and bars[bi.end_idx].l < zs.zd:
                leave_idx = k
                break
            # 未破界：中枢内震荡，继续看下一笔
        if leave_idx is None:
            continue
        leave = bi_list[leave_idx]
        # 第一次回试 = 离开笔后的第一根反向已确认笔
        for back in bi_list[leave_idx + 1 :]:
            if not back.sure:
                break
            if back.dir is leave.dir:
                continue  # 同向笔（离开延续），跳过
            if leave.dir is Direction.UP:
                # 三买：回试低点不跌破 ZG
                if bars[back.end_idx].l > zs.zg:
                    bsp_out.append(
                        BSPoint(
                            idx=back.end_idx,
                            bstype=3,
                            dir=Direction.UP,
                            level=1,
                            sure=True,
                            source=SOURCE,
                        )
                    )
            else:
                # 三卖：回试高点不升破 ZD
                if bars[back.end_idx].h < zs.zd:
                    bsp_out.append(
                        BSPoint(
                            idx=back.end_idx,
                            bstype=3,
                            dir=Direction.DOWN,
                            level=1,
                            sure=True,
                            source=SOURCE,
                        )
                    )
            break  # 只看第一次回试
    return bsp_out
