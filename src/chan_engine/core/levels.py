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

M7-3 G6 增补：九段升级（课 33）移入 core——``detect_nine_bi_zs`` 笔级
播种（引导笔定方向 + 反向笔对重叠 + sure 笔延伸）+ 3 子中枢重合门控 →
level-2 中枢；``apply_nine_bi_upgrade`` 吞并 span 内段合成中间产物。
recursion 列 ZS-003 由此转 PASS（2026-08-28 校准矩阵实证）。
"""

from __future__ import annotations

from chan_engine.core.model import SegType
from chan_engine.core.segments import _bi_high_low
from chan_engine.spec.model import Bar, Bi, Direction, ZhongShu

SOURCE = "recursion"


def _has_overlap_strict(low1: float, high1: float, low2: float, high2: float) -> bool:
    """严格重叠（不含边界），对齐 chanpy has_overlap(equal=False)。"""
    return high2 > low1 and high1 > low2


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


# ── M7-3 G6：九段升级（课 33，claim-20070302-001-b） ──

def detect_nine_bi_zs(bi_list: list[Bi], bars: list[Bar]) -> list[ZhongShu]:
    """笔级九段升级直探：≥9 笔连续重叠 → 更大级别中枢（level=2）。

    口径（移植自 czsc 适配器 M2-3 实现，core 化；设计 §6.4）：
    - 播种：引导笔（bi_list[0]）定方向，**反向笔对**严格重叠成种子中枢
      （start=反向笔a.start_idx，end=反向笔b.end_idx，zd/zg=两笔重叠区）；
    - 延伸：种子确立后，后续**已确认**反向笔与 [zd,zg] 严格重叠则延展 end
      （末位未确认笔不延伸，对齐 M2-3 口径；zd/zg 不随延伸更新）；
    - 门控（唯一落改条件）：范围内笔数 ≥9，且前 9 笔分 3 组（每组 3 笔）
      子中枢各自成立，且 3 子中枢重合区间成立（max(sub_zd) < min(sub_zg)）；
    - 发射：level=2 中枢，zd/zg=重合区间，start/end=种子延伸后 span。
      只发射升级产物（3 个 level-1 子中枢为中间产物，ZS-003 expect 口径）。
    """
    if len(bi_list) < 10:  # 引导笔 + ≥9 笔才可能凑齐 9 段
        return []
    seg_dir = bi_list[0].dir
    seeds: list[ZhongShu] = []
    free: list[Bi] = []  # 等待配对的反向笔队列
    for bi in bi_list[1:]:
        if bi.dir is seg_dir:
            continue
        if not free and seeds:
            last = seeds[-1]
            lo, hi = _bi_high_low(bi, bars)
            if bi.sure and _has_overlap_strict(last.zd, last.zg, lo, hi):
                last.end_idx = bi.end_idx  # 只延展 end，不更新 zd/zg
                continue
        free.append(bi)
        if len(free) >= 2:
            a, b = free[-2], free[-1]
            alo, ahi = _bi_high_low(a, bars)
            blo, bhi = _bi_high_low(b, bars)
            zd, zg = max(alo, blo), min(ahi, bhi)
            if zg > zd:
                seeds.append(ZhongShu(zd=zd, zg=zg, start_idx=a.start_idx,
                                      end_idx=b.end_idx, level=1, sure=True,
                                      source=SOURCE))
                free = []

    upgraded: list[ZhongShu] = []
    for z in seeds:
        in_range = [b for b in bi_list
                    if b.start_idx >= z.start_idx and b.end_idx <= z.end_idx]
        if len(in_range) < 9:
            continue
        nine = in_range[:9]
        sub_ranges: list[tuple[float, float]] = []
        for i in range(0, 9, 3):
            lows, highs = [], []
            for b in nine[i : i + 3]:
                lo, hi = _bi_high_low(b, bars)
                lows.append(lo)
                highs.append(hi)
            sub_zd, sub_zg = max(lows), min(highs)
            if sub_zg <= sub_zd:
                break  # 子中枢不成立
            sub_ranges.append((sub_zd, sub_zg))
        if len(sub_ranges) != 3:
            continue
        zd2 = max(r[0] for r in sub_ranges)
        zg2 = min(r[1] for r in sub_ranges)
        if zg2 <= zd2:
            continue
        upgraded.append(ZhongShu(zd=zd2, zg=zg2, start_idx=z.start_idx,
                                 end_idx=z.end_idx, level=2, sure=True,
                                 source=SOURCE))
    return upgraded


def apply_nine_bi_upgrade(
    zs_list: list[ZhongShu], bi_list: list[Bi], bars: list[Bar]
) -> list[ZhongShu]:
    """九段升级后处理：命中时吞并升级 span 内的段合成中枢（中间产物不发射）。

    吞并规则：既有 zs 起点落在升级中枢 [start_idx, end_idx] 内 → 视为该
    九段结构的中间产物移除（课 33"9 段即构成更大级别中枢，归属唯一确定"，
    ZS-003 expect 只列升级后 L2）。未命中时原样返回（零改动）。
    """
    upgraded = detect_nine_bi_zs(bi_list, bars)
    if not upgraded:
        return zs_list
    kept = [
        z for z in zs_list
        if not any(u.start_idx <= z.start_idx <= u.end_idx for u in upgraded)
    ]
    return kept + upgraded
