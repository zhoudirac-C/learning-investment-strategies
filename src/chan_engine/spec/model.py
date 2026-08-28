"""归一数据模型（M1 spec 层）。

纯数据容器，不含任何缠论逻辑。两实现（chan.py / czsc）的输出与用例 expect
都归一到这些结构后逐字段 diff。

字段口径（实施计划 Task 1）：
- Bar      = (ts, o, h, l, c, vol)
- FX       = (idx, type, sure)
- Bi       = (start_idx, end_idx, dir, sure)
- Segment  = (start_bi, end_bi, dir, sure)
- ZhongShu = (zd, zg, start_idx, end_idx, level, sure)
- BSPoint  = (idx, bstype(1/2/3), dir, level, sure)

每个结构元素另带 ``source: str``（产出该元素的实现名，如 "chanpy"/"czsc"，
spec 层留空）。``sure`` 对应缠论"右侧确认"语义：未确认为 False。

方向约定：``FX.type`` 取终结于该分型的笔的方向——顶分型=UP，底分型=DOWN。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 避免 spec ← core 运行期反向依赖（M7-3 走势类型状态机）
    from chan_engine.core.trend import TrendState


class Direction(Enum):
    """走势方向。"""

    UP = "up"
    DOWN = "down"


@dataclass
class Bar:
    """单根 K 线。``ts`` 为递增序号或时间戳，由构造方决定。"""

    ts: int
    o: float
    h: float
    l: float
    c: float
    vol: float


@dataclass
class FX:
    """分型。``idx`` 为分型中间 K 线的 Bar 索引。"""

    idx: int
    type: Direction  # UP=顶分型，DOWN=底分型（= 终结于该分型的笔的方向）
    sure: bool = True
    source: str = ""


@dataclass
class Bi:
    """笔。``start_idx``/``end_idx`` 为端点分型的 Bar 索引。"""

    start_idx: int
    end_idx: int
    dir: Direction
    sure: bool = True
    source: str = ""


@dataclass
class Segment:
    """线段。``start_bi``/``end_bi`` 为端点笔在笔表中的序号。"""

    start_bi: int
    end_bi: int
    dir: Direction
    sure: bool = True
    source: str = ""


@dataclass
class ZhongShu:
    """中枢。``zd``=低点上沿（ZD），``zg``=高点下沿（ZG）；区间为 [zd, zg]。"""

    zd: float
    zg: float
    start_idx: int
    end_idx: int
    level: int = 1
    sure: bool = True
    source: str = ""


@dataclass
class BSPoint:
    """买卖点。``bstype`` 只取 1/2/3（一/二/三类）。

    ``backchi_type``（M7-3 G3）：背驰前提校验标注，仅 bstype=1 时有值
    （"trend_div" 趋势背驰 / "consolidation_div" 盘整背驰），其余留空。
    不参与校准 diff（``_TABLE_FIELDS`` 显式字段表外）。
    """

    idx: int
    bstype: int
    dir: Direction
    level: int = 1
    sure: bool = True
    source: str = ""
    backchi_type: str = ""

    def __post_init__(self) -> None:
        if self.bstype not in (1, 2, 3):
            raise ValueError(f"bstype must be 1/2/3, got {self.bstype!r}")


# NormalizedChart 五张表的合法表名（na_fields 取值范围，Task 5/6 使用）。
CHART_TABLES = ("fx", "bi", "seg", "zs", "bsp")


@dataclass
class NormalizedChart:
    """一个实现对一段 K 线的完整归一分解结果：五张表。

    ``na_fields``：该实现不支持的表名集合（CHART_TABLES 子集），
    如 czsc 标 {"seg", "bsp"}；diff 时跳过这些表的比对（Task 5/6 使用）。
    """

    fx: list[FX] = field(default_factory=list)
    bi: list[Bi] = field(default_factory=list)
    seg: list[Segment] = field(default_factory=list)
    zs: list[ZhongShu] = field(default_factory=list)
    bsp: list[BSPoint] = field(default_factory=list)
    na_fields: set[str] = field(default_factory=set)
    # M7-3 走势类型状态机输出（新增字段，不参与 diff/校准比对）：
    # 最高 level 同级别中枢的 analyze_trend 结果（仓位性质的结构化根据）。
    trend: "TrendState | None" = None
