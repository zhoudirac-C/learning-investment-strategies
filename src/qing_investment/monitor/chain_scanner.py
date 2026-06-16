"""Qing-Agent 监控引擎 — 产业链感知扫描器 (Phase 2)

当核心标的大涨或涨停买不到时，自动推荐同产业链还没涨的环节，推荐替代标的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ChainAlternative:
    """产业链替代标的。"""

    code: str
    name: str
    chain_position: str
    segment: str
    reason: str


class ChainAwareScanner:
    """基于产业链关系的智能扫描器。"""

    def find_alternatives(
        self,
        pumped_stock: str,
        direction: dict,
    ) -> list[ChainAlternative]:
        """找一个已经涨了的标的，推荐同链还没涨的环节标的。

        Args:
            pumped_stock: 已经大涨/涨停的股票代码（如 000636.SZ）
            direction: direction_pool 中的单个 direction dict
        """
        chain = direction.get("industry_chain", {})
        if not chain:
            return []

        # 定位 pumped_stock 所在的 segment
        pumped_segment = None
        for position, segments in chain.items():
            for segment in segments or []:
                for stock in segment.get("stocks", []) or []:
                    if str(stock.get("code", "")) == pumped_stock:
                        pumped_segment = {"position": position, **segment}
                        break
                if pumped_segment:
                    break
            if pumped_segment:
                break

        if pumped_segment is None:
            return []

        alternatives: list[ChainAlternative] = []
        for position, segments in chain.items():
            if position == pumped_segment["position"]:
                continue
            for segment in segments or []:
                if segment.get("pumped", False):
                    continue
                for stock in segment.get("stocks", []) or []:
                    code = str(stock.get("code", ""))
                    name = stock.get("name", "")
                    if code and name:
                        alternatives.append(
                            ChainAlternative(
                                code=code,
                                name=name,
                                chain_position=position,
                                segment=segment.get("segment", ""),
                                reason=(
                                    f"{pumped_stock} 所在的 {pumped_segment['segment']} 已涨，"
                                    f"推荐同方向 {position} 的 {segment.get('segment')} 低位标的"
                                ),
                            )
                        )
        return alternatives
