"""M3-4 GOLD 探索：日线级别三买代理（箱体突破 + 首次回试不破）。

动机（GOLD-001/002 根因）：课文日线级三买（工行 2006-12-14 / 北辰实业
2006-11-14）的"次级别离开+回试"是 30 分钟级结构，日线上 chanpy/czsc 仅画
1~3 笔，回试段无法成笔（回试低点与相邻 bar 不满足分型间距），笔级/分型级
构造均不可达。但课文例子的中枢语义实为**长期横盘箱体**：

- 中枢区域 = 突破前 ≥ ``MIN_CONSOLIDATION_BARS`` 根 bar 的横盘箱体，
  箱体上沿 = 此前全部 bar 的最高价（GOLD-002 课文注："区域上沿 ≈4.05，
  上市首日 idx0 高点"）；
- 向上离开 = 首根**收盘**站上箱体上沿的 bar（突破 bar）；
- 回试 = 突破拉升后首次滞涨回调（连续 h ≤ 拉升最高点的 bar 段）；
- 不破 = 回试段最低点 > 箱体上沿 → 三买，落在回试段最低低点所在 bar
  （课 20：必须是第一次回试）。

与笔级三买（``backchi.detect_third_type_bsp``）的关系：本检测只在笔级
结构过粗（递归层 zs/bsp 双空）时由 engine 兜底调用，是日线金标的务实
代理，非通用缠论构造；差异与局限登记 ADR。
"""

from __future__ import annotations

from chan_engine.spec.model import Bar, BSPoint, Direction

SOURCE = "recursion"
MIN_CONSOLIDATION_BARS = 15


def detect_box_third_buy(
    bars: list[Bar], *, min_consolidation: int = MIN_CONSOLIDATION_BARS
) -> list[BSPoint]:
    """箱体突破 + 首次回试不破 → 日线三买（至多一条，找不到返回空）。

    扫描首个"收盘突破箱顶"的 bar；其首次回试段最低点 > 箱顶 → 三买
    落于回试段最低低点 bar；回试破箱顶则本次突破不成立，继续向后
    扫描下一次箱体突破（箱体随历史 bar 自然演进）。
    """
    n = len(bars)
    b = min_consolidation
    while b < n:
        box_top = max(bars[k].h for k in range(b))
        if bars[b].c <= box_top:
            b += 1
            continue
        # 突破 bar = b；拉升段 = 其后连续创新高的 bar
        run_high = bars[b].h
        j = b + 1
        while j < n and bars[j].h > run_high:
            run_high = bars[j].h
            j += 1
        # 回试段 = 连续 h ≤ run_high 的 bar（首次滞涨回调）
        p_start = j
        while j < n and bars[j].h <= run_high:
            j += 1
        pullback = list(range(p_start, j))
        if not pullback:
            return []  # 突破后一路新高无回试 → 无三买
        low_bar = min(pullback, key=lambda k: bars[k].l)
        if bars[low_bar].l > box_top:
            return [
                BSPoint(
                    idx=low_bar,
                    bstype=3,
                    dir=Direction.UP,
                    level=1,
                    sure=True,
                    source=SOURCE,
                )
            ]
        # 首次回试破箱顶 → 本次突破不成立，从回试段后继续找下一箱体
        b = j
    return []
