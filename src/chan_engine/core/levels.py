"""M3-2: LevelTree 多级中枢合成。

课 35/84 递归口径（BC-002 expect 实证）：
- 三个连续 L_N 走势类型构成 L_{N+1} 走势类型：**进入段 + 中枢段 + 离开段**
  （方向模式 X, ~X, X）；
- **中枢段**的内部中枢即 L_{N+1} 中枢（标记 level=N+1）——BC-002 实证：
  level-2 zs = 中枢段 B2（bi3-5）三笔重叠 [23.9, 26.2]，而非 3 段互叠
  （3 段互叠得 [23.3, 26.2]，zd 与 expect 不符）；
- **离开段**的内部中枢保持 level=N（区间套次级别，供背驰精确定位）；
- 进入段的内部中枢不发射（历史段，非当前区间套分析对象）。

段内中枢 = 连续三笔重叠区间（课 17：``ZD=max(三笔低点)``、``ZG=min(三笔高点)``，
严格 ``ZG > ZD``）。当前 L0 段均为最小 3 笔段（M3-1），更长段的内部多中枢
构造留待 M3-5 泛化。

与设计文档 §6.2 的差异（登记 ADR）：设计文档写"3×L0 重叠 → L1 中枢"，
BC-002 expect 实证为"中枢段内部三笔重叠"。以 expect 语料为准。
"""

from __future__ import annotations

from chan_engine.core.model import SegType
from chan_engine.core.segments import _bi_high_low
from chan_engine.spec.model import Bar, Bi, Direction, ZhongShu

SOURCE = "recursion"


def _segment_zhongshu(
    seg: SegType, bi_list: list[Bi], bars: list[Bar]
) -> ZhongShu | None:
    """段内三笔重叠中枢（课 17）；段 <3 笔或无重叠返回 None。

    返回 ZhongShu 的 level 由调用方按角色标注（中枢段→L+1，离开段→L），
    本函数只算区间与端点，level 置 1 占位。
    """
    span = bi_list[seg.start_bi : seg.end_bi + 1]
    if len(span) < 3:
        return None
    triple = span[:3]  # 最小 3 笔段即全部三笔
    lows: list[float] = []
    highs: list[float] = []
    for bi in triple:
        lo, hi = _bi_high_low(bi, bars)
        lows.append(lo)
        highs.append(hi)
    zd = max(lows)
    zg = min(highs)
    if zg <= zd:
        return None
    return ZhongShu(
        zd=zd,
        zg=zg,
        start_idx=triple[0].start_idx,
        end_idx=triple[-1].end_idx,
        level=1,
        sure=True,
        source=SOURCE,
    )


def find_trend_patterns(segments: list[SegType]) -> list[tuple[int, int, int]]:
    """扫描 L0 段序列，识别 进入+中枢+离开 三件套（方向模式 X,~X,X）。

    返回三件套的起始索引三元组列表（(i, i+1, i+2)）。命中后跳过这三段
    继续扫描（BC-002：A2+B2+C2 一锤子买卖）。供 zs 合成与 bsp 检测共用。
    """
    patterns: list[tuple[int, int, int]] = []
    i = 0
    while i + 2 < len(segments):
        s0, s1, s2 = segments[i], segments[i + 1], segments[i + 2]
        if s0.dir is s2.dir and s1.dir is not s0.dir:
            patterns.append((i, i + 1, i + 2))
            i += 3
        else:
            i += 1
    return patterns


def synthesize_level_zs(
    segments: list[SegType], bi_list: list[Bi], bars: list[Bar]
) -> list[ZhongShu]:
    """对三件套合成多级中枢。

    - 中枢段（中间段）内部中枢 → level+1；
    - 离开段（末段）内部中枢 → level。
    """
    zs_out: list[ZhongShu] = []
    for _, i1, i2 in find_trend_patterns(segments):
        core = _segment_zhongshu(segments[i1], bi_list, bars)
        if core is not None:
            core.level = 2  # 中枢段 → level-2
            zs_out.append(core)
        leave = _segment_zhongshu(segments[i2], bi_list, bars)
        if leave is not None:
            leave.level = 1  # 离开段 → level-1
            zs_out.append(leave)
    return zs_out


def synthesize_standalone_zs(
    segments: list[SegType], bi_list: list[Bi], bars: list[Bar]
) -> list[ZhongShu]:
    """未被三件套消费的**已确认**段：内部三笔重叠 → level-1 中枢。

    BSP-003 锚：仅 2 段（无三件套），首段 bi0-2 全 sure 且重叠
    → 发射 (11.4, 14.0, 1→16, level=1)；次段含未确认笔 bi5 → 抑制
    （结构未定型，不出中枢）。三件套内的进入段/中枢段/离开段由
    ``synthesize_level_zs`` 按角色处理，此处跳过。
    """
    consumed = {i for triple in find_trend_patterns(segments) for i in triple}
    zs_out: list[ZhongShu] = []
    for k, seg in enumerate(segments):
        if k in consumed or not seg.sure:
            continue
        z = _segment_zhongshu(seg, bi_list, bars)
        if z is not None:
            z.level = 1
            zs_out.append(z)
    return zs_out
