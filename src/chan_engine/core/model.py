"""M3 递归层数据容器。

L0 走势类型（SegType，即线段）：连续若干笔构成的同向摆动。
与 ``spec.model`` 的归一五表对齐——本层对象最终归一为 zs/bsp 表（带 level 字段）
输出给校准门比对，自身只做递归计算的中间载体。
"""

from __future__ import annotations

from dataclasses import dataclass

from chan_engine.spec.model import Direction


@dataclass
class SegType:
    """L0 走势类型（线段）。

    ``start_bi``/``end_bi`` 为首末笔在归一笔表中的序号（end 含）。
    ``dir`` 为段方向 = 首笔方向。``high``/``low`` 为段内全部笔的极值包络
    （供后续 3×L0 重叠 / 区间套计算用）。``sure`` 透传"右侧确认"语义：
    段末端遇未确认笔（sure=False）则该段 sure=False。
    """

    start_bi: int
    end_bi: int
    dir: Direction
    high: float
    low: float
    sure: bool = True
    source: str = ""

    @property
    def bi_count(self) -> int:
        return self.end_bi - self.start_bi + 1
