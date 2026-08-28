"""M3-3: 背驰判断 + 多级买卖点生成。M7-3 G7 增补 MACD 主口径。

背驰口径（BC-002 expect + 课 27 精确大转折点寻找程序定理实证）：

- **主口径 = MACD 柱面积**（``|hist|`` 求和，core/macd.py；v1.3 改判，
  与 UP 课程 P2/P4 及 skill 现行纪律一致）；
- **对照口径 = Σ|Δc|**（段内全部笔 |收盘变化| 之和，校准门原口径，
  ``area_mode="sigma"`` 保留，校准用例 expect 断言不动，两口径测试层隔离）。
- **level-N+1 背驰**：进入段面积 vs 离开段面积（同向比较），``离开 < 进入`` →
  大级别背驰 → 在离开段终点出 一买/一卖（level=N+1）。
  BC-002：A2=10.84 > C2=6.04 → level-2 一买@46。
- **level-N 背驰**：离开段内 首同向笔 vs 末同向笔（``a1`` vs ``c1``），``末 < 首`` →
  次级别背驰 → 同一点再出 一买/一卖（level=N）。
  BC-002：a1=2.88 > c1=2.08 → level-1 一买@46。
- **买卖点方向**：下跌走势（离开段向下）背驰 → 一买 ``dir=up``；
  上涨走势（离开段向上）背驰 → 一卖 ``dir=down``。
- sure：形成即确认（附录 C.1 zs/bsp 约定）。

背驰一买/一卖之外另含：二类买卖点（``detect_second_type_bsp``，M7-3 G4，
一买后首次回调不破低点，反向笔代理过渡口径）；背驰前提校验
（``classify_backchi_type``，M7-3 G3，trend_div / consolidation_div 标注）。
第三类买卖点（回试不破 ZG/ZD）属走势类型判定（BSP-003），同文件
``detect_third_type_bsp``。
"""

from __future__ import annotations

from chan_engine.core.macd import calc_macd
from chan_engine.core.model import SegType
from chan_engine.spec.model import Bar, Bi, BSPoint, Direction, ZhongShu

SOURCE = "recursion"

#: 背驰面积口径：macd（主，v1.3 改判）/ sigma（Σ|Δc|，校准对照）
AREA_MODES = ("macd", "sigma")


def _bi_area(bi: Bi, bars: list[Bar]) -> float:
    """单笔面积（Σ|Δc| 对照口径）：|笔终点收盘 − 笔起点收盘|。"""
    return abs(float(bars[bi.end_idx].c) - float(bars[bi.start_idx].c))


def _segment_area(seg: SegType, bi_list: list[Bi], bars: list[Bar]) -> float:
    """段面积（Σ|Δc| 对照口径） = 段内全部笔面积之和。"""
    return sum(_bi_area(bi_list[k], bars) for k in range(seg.start_bi, seg.end_bi + 1))


def _bi_area_macd(bi: Bi, hist: list[float]) -> float:
    """单笔面积（MACD 主口径）：笔端点 bar 闭区间 |hist| 求和。"""
    return sum(abs(hist[i]) for i in range(bi.start_idx, bi.end_idx + 1))


def _segment_area_macd(seg: SegType, bi_list: list[Bi], hist: list[float]) -> float:
    """段面积（MACD 主口径） = 段首笔起点 bar ~ 末笔终点 bar 的 |hist| 和。"""
    start = bi_list[seg.start_bi].start_idx
    end = bi_list[seg.end_bi].end_idx
    return sum(abs(hist[i]) for i in range(start, end + 1))


def _segment_internal_backchi(
    seg: SegType, bi_list: list[Bi], bars: list[Bar],
    hist: list[float] | None = None, area_mode: str = "macd",
) -> bool:
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
    if area_mode == "macd":
        assert hist is not None
        first_area = _bi_area_macd(directional[0], hist)
        last_area = _bi_area_macd(directional[-1], hist)
    else:
        first_area = _bi_area(directional[0], bars)
        last_area = _bi_area(directional[-1], bars)
    return last_area < first_area


def _bsp_dir_for(seg_dir: Direction) -> Direction:
    """离开段方向 → 买卖点方向：下跌背驰→一买(up)，上涨背驰→一卖(down)。"""
    return Direction.UP if seg_dir is Direction.DOWN else Direction.DOWN


def classify_backchi_type(
    zs_list: list[ZhongShu], current_zs: ZhongShu, trend_dir: Direction
) -> str:
    """背驰前提校验（G3，L15"没有趋势没有背驰"，设计 §6.2）。

    当前中枢（三件套中枢段的 L2 中枢）之前存在**同级别、同向不重叠**中枢
    → 走势为趋势 → ``trend_div``（标准一买/一卖）；否则 ``consolidation_div``
    （盘整背驰——报告必须标注，防误报为反转信号）。

    同向不重叠（与 trend.py 严格口径一致）：下跌趋势中前中枢整体在当前上方
    （prior.zd >= current.zg）；上涨镜像（prior.zg <= current.zd）。
    """
    prior_same_dir = 0
    for z in zs_list:
        if z is current_zs or z.level != current_zs.level:
            continue
        if z.start_idx >= current_zs.start_idx:
            continue  # 只计当前中枢之前的中枢
        if trend_dir is Direction.DOWN and z.zd >= current_zs.zg:
            prior_same_dir += 1
        elif trend_dir is Direction.UP and z.zg <= current_zs.zd:
            prior_same_dir += 1
    return "trend_div" if prior_same_dir >= 1 else "consolidation_div"


def detect_backchi_bsp(
    segments: list[SegType], bi_list: list[Bi], bars: list[Bar],
    area_mode: str = "macd",
    zs_list: list[ZhongShu] | None = None,
) -> list[BSPoint]:
    """对 进入+中枢+离开 三件套做背驰判断，产出多级买卖点。

    扫描方向模式 X,~X,X 的三段；对每组：
    - level-2 背驰（进入段 vs 离开段面积）→ level=2 买卖点；
    - level-1 背驰（离开段内首末同向笔）→ level=1 买卖点；
    两点同落在离开段末笔终点。

    ``area_mode``：'macd'（主口径，v1.3 改判）/ 'sigma'（Σ|Δc| 校准对照）。
    ``zs_list``（M7-3 G3）：提供时对 bstype=1 标注 ``backchi_type``
    （trend_div / consolidation_div）；缺省留空（向后兼容既有直调）。
    """
    if area_mode not in AREA_MODES:
        raise ValueError(f"非法 area_mode: {area_mode!r}（仅 {AREA_MODES}）")
    from chan_engine.core.levels import find_trend_patterns

    hist = calc_macd([float(b.c) for b in bars])[2] if area_mode == "macd" else None

    def _core_zs(s1: SegType) -> ZhongShu | None:
        """三件套中枢段的 L2 中枢（与 synthesize_level_zs 的端点口径匹配）。"""
        if zs_list is None or s1.end_bi - s1.start_bi < 2:
            return None
        start = bi_list[s1.start_bi].start_idx
        end = bi_list[s1.start_bi + 2].end_idx  # 段内中枢取前三笔（M3-2 口径）
        for z in zs_list:
            if z.level == 2 and z.start_idx == start and z.end_idx == end:
                return z
        return None

    bsp_out: list[BSPoint] = []
    for i0, i1, i2 in find_trend_patterns(segments):
        s0, s2 = segments[i0], segments[i2]
        end_bar_idx = bi_list[s2.end_bi].end_idx
        bdir = _bsp_dir_for(s2.dir)
        backchi_type = ""
        if zs_list is not None:
            core = _core_zs(segments[i1])
            # 走势方向 = 离开段方向；中枢段无内部中枢时按盘整背驰（保守标注）
            backchi_type = classify_backchi_type(zs_list, core, s2.dir) \
                if core is not None else "consolidation_div"
        # level-2 背驰：进入段 vs 离开段
        if area_mode == "macd":
            assert hist is not None
            a_enter = _segment_area_macd(s0, bi_list, hist)
            a_leave = _segment_area_macd(s2, bi_list, hist)
        else:
            a_enter = _segment_area(s0, bi_list, bars)
            a_leave = _segment_area(s2, bi_list, bars)
        if a_leave < a_enter:
            bsp_out.append(
                BSPoint(idx=end_bar_idx, bstype=1, dir=bdir, level=2, sure=True,
                        source=SOURCE, backchi_type=backchi_type)
            )
        # level-1 背驰：离开段内 a1 vs c1
        if _segment_internal_backchi(s2, bi_list, bars, hist, area_mode):
            bsp_out.append(
                BSPoint(idx=end_bar_idx, bstype=1, dir=bdir, level=1, sure=True,
                        source=SOURCE, backchi_type=backchi_type)
            )
    return bsp_out


def detect_second_type_bsp(
    bsp_list: list[BSPoint], bi_list: list[Bi], bars: list[Bar]
) -> list[BSPoint]:
    """第二类买卖点（M7-3 G4，课 17 定义 + 安全性证明，设计 §6.3）。

    一买后**第一次次级别回调**低点不破一买低点 → 二买；一卖镜像
    （回抽高点不破一卖高点 → 二卖）。过渡期"次级别回调"用反向笔代理
    （仲裁 ⑤），M7-4 起由真 60m 切片确认替换（未确认则标 sure=False）。
    安全性由分解定理保证（一买后已走两段，必有第三段向上），非概率。

    - 回调笔 = 一买点之后第一根反向笔；只取第一次（破低/破高则该一买/一卖
      不出二类点，首次回调即破坏）。
    - ``sure`` 透传回调笔的右侧确认状态；level 镜像源一买/一卖。
    - 同一回调点被多级一买命中 → 去重保最高 level。
    """
    out: dict[tuple[int, Direction], BSPoint] = {}
    for bsp in bsp_list:
        if bsp.bstype != 1:
            continue
        if bsp.dir is Direction.UP:  # 一买：找第一根向下回调笔
            ref = float(bars[bsp.idx].l)
            counter_dir = Direction.DOWN
        else:  # 一卖：找第一根向上回抽笔
            ref = float(bars[bsp.idx].h)
            counter_dir = Direction.UP
        for bi in bi_list:
            if bi.start_idx < bsp.idx or bi.dir is not counter_dir:
                continue
            # 第一根反向笔即判定（无论成立与否都停止——只取第一次回调）
            if bsp.dir is Direction.UP:
                holds = float(bars[bi.end_idx].l) > ref
            else:
                holds = float(bars[bi.end_idx].h) < ref
            if holds:
                key = (bi.end_idx, bsp.dir)
                prev = out.get(key)
                if prev is None or bsp.level > prev.level:
                    out[key] = BSPoint(
                        idx=bi.end_idx, bstype=2, dir=bsp.dir, level=bsp.level,
                        sure=bi.sure, source=SOURCE,
                    )
            break
    return list(out.values())


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
