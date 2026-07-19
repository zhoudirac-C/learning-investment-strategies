"""harness 适配器协议（M1）。

各实现（chan.py / czsc）的适配器遵循同一协议：吃 ``list[Bar]``，
吐归一后的 ``NormalizedChart``，并自带实现名与配置快照（偏差分析用）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from chan_engine.spec.model import Bar, NormalizedChart


@runtime_checkable
class ChartAdapter(Protocol):
    """缠论实现 → 归一走势分解 的适配器协议。"""

    name: str
    """实现名，同时写入每个归一元素的 ``source`` 字段。"""

    config_snapshot: dict
    """该实现运行时的完整配置快照（JSON 可序列化），供口径偏差分析对照。"""

    def run(self, bars: list[Bar]) -> NormalizedChart:
        """对一段 K 线做完整分解，返回归一五表。只做搬运归一，不做口径修正。"""
        ...
