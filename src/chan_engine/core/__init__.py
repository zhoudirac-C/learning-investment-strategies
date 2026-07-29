"""缠论引擎核心层（M3 递归层）。

自建级别递归：归一 bi 表 → L0 走势类型（线段）→ 多级中枢 → 多级买卖点。
两库（chanpy/czsc）均无级别递归，本层独立实现（课 35/84 口径）。

子模块：
- ``model``    ：L0 走势类型（SegType）等数据容器；
- ``segments`` ：bi 表 → L0 走势类型分组；
- ``levels``   ：L0 → 多级中枢合成（LevelTree）；
- ``backchi``  ：背驰判断 + 多级买卖点；
- ``engine``   ：顶层递归入口，供适配器/校准门调用。
"""

from chan_engine.core.backchi import detect_backchi_bsp
from chan_engine.core.levels import synthesize_level_zs
from chan_engine.core.model import SegType
from chan_engine.core.segments import build_l0_segments

__all__ = [
    "SegType",
    "build_l0_segments",
    "synthesize_level_zs",
    "detect_backchi_bsp",
]
