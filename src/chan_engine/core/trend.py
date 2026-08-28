"""M7-3 G1/G2：走势类型状态机（课 17/18/20，设计 §6.1）。

- **盘整** = 完成走势只含 1 个中枢；**趋势** = ≥2 个**依次同向、互不重叠**
  （区间严格无交集，单点相接不算重叠——与校准门 has_overlap 严格口径一致）的中枢。
- **中枢三演化**（课 18/20）：
  - 延伸：只有 1 个中枢在延续；
  - 新生：新中枢与前一同向不重叠 → 趋势延伸；
  - 扩张：相邻两中枢区间重叠 → 级别扩张（级别延续定理二，
    claim-20070105-001-a/b），整体仍归盘整。

输入为**同级别**中枢列表（调用方按 level 过滤）。``walk_type`` 是仓位性质
（反弹仓 vs 反转仓）的结构化根据，取代 adapter 层启发式（设计 §6.1）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from chan_engine.spec.model import Direction, ZhongShu

WALK_TYPES = ("trend", "consolidation", "unknown")
LAST_EVENTS = ("extension", "new", "expansion", "")


@dataclass
class TrendState:
    """走势类型判定结果（某一级别的中枢序列视角）。"""

    walk_type: str                # trend / consolidation / unknown
    direction: Direction | None   # 趋势方向（非 trend 为 None）
    zs_count: int
    zs_list: list[ZhongShu] = field(default_factory=list)
    last_event: str = ""          # extension / new / expansion / ""


def _nonoverlap_dir(prev: ZhongShu, nxt: ZhongShu) -> Direction | None:
    """相邻两中枢严格不重叠时的相对方向；重叠返回 None。"""
    if nxt.zd >= prev.zg:
        return Direction.UP
    if nxt.zg <= prev.zd:
        return Direction.DOWN
    return None


def analyze_trend(zs_list: list[ZhongShu]) -> TrendState:
    """同级别中枢序列 → 走势类型状态。

    趋势判定：全部相邻对依次同向且不重叠；任一对重叠（扩张）或方向切换
    则非单一趋势（consolidation）。``last_event`` 描述最末一对的演化：
    重叠 → expansion；不重叠 → new；单中枢 → extension。
    """
    zs = sorted(zs_list, key=lambda z: (z.start_idx, z.end_idx))
    n = len(zs)
    if n == 0:
        return TrendState(walk_type="unknown", direction=None, zs_count=0, zs_list=zs)
    if n == 1:
        return TrendState(walk_type="consolidation", direction=None,
                          zs_count=1, zs_list=zs, last_event="extension")

    pair_dirs = [_nonoverlap_dir(a, b) for a, b in zip(zs, zs[1:])]
    last_event = "expansion" if pair_dirs[-1] is None else "new"

    if all(d is not None and d is pair_dirs[0] for d in pair_dirs):
        return TrendState(walk_type="trend", direction=pair_dirs[0],
                          zs_count=n, zs_list=zs, last_event=last_event)
    return TrendState(walk_type="consolidation", direction=None,
                      zs_count=n, zs_list=zs, last_event=last_event)
