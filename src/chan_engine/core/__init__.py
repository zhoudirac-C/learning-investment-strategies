"""缠论引擎核心层（M3 递归层 + M7-3 理论补全）。

自建级别递归：归一 bi 表 → L0 走势类型（线段）→ 多级中枢 → 多级买卖点。
两库（chanpy/czsc）均无级别递归，本层独立实现（课 35/84 口径）。

子模块：
- ``model``    ：L0 走势类型（SegType）等数据容器；
- ``segments`` ：bi 表 → L0 走势类型分组；
- ``levels``   ：L0 → 多级中枢合成（LevelTree）+ 九段升级（M7-3 G6，课 33）；
- ``backchi``  ：背驰判断 + 多级买卖点（一/二/三类；MACD 柱面积主口径 +
  Σ|Δc| 对照——M7-3 G7；背驰前提校验 backchi_type——M7-3 G3）；
- ``macd``     ：MACD 计算（M7-3 G7，首根 close 种子，与 skill 逐位一致）；
- ``trend``    ：走势类型状态机（M7-3 G1/G2，盘整/趋势/三演化）；
- ``engine``   ：顶层递归入口（RecursionEngine），供校准门调用。
"""

from chan_engine.core.backchi import (
    classify_backchi_type,
    detect_backchi_bsp,
    detect_second_type_bsp,
    detect_third_type_bsp,
)
from chan_engine.core.levels import (
    apply_nine_bi_upgrade,
    detect_nine_bi_zs,
    find_trend_patterns,
    synthesize_level_zs,
    synthesize_standalone_zs,
)
from chan_engine.core.macd import calc_macd
from chan_engine.core.model import SegType
from chan_engine.core.segments import build_l0_segments
from chan_engine.core.trend import TrendState, analyze_trend

__all__ = [
    "SegType",
    "TrendState",
    "analyze_trend",
    "apply_nine_bi_upgrade",
    "build_l0_segments",
    "calc_macd",
    "classify_backchi_type",
    "detect_backchi_bsp",
    "detect_nine_bi_zs",
    "detect_second_type_bsp",
    "detect_third_type_bsp",
    "find_trend_patterns",
    "synthesize_level_zs",
    "synthesize_standalone_zs",
]
