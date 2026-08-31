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

    def find_alternatives_from_kb(
        self,
        pumped_stock: str,
        *,
        base_dir=None,
    ) -> list[ChainAlternative]:
        """M0-Chain 知识库 fallback（2026-08-31 接线）。

        direction_pool 无 industry_chain 配置或其他环节全部已涨时，从
        knowledge/industry-chains 找同链其他环节标的。阶段0-观察链不推荐
        （观察态不构成机会）。知识库不可用返回 []。
        """
        code6 = str(pumped_stock).split(".")[0]
        try:
            from investment_engine.industry_chain.store import (
                list_chains, load_chain,
            )
        except Exception:  # noqa: BLE001 - 非 Hermes 环境无 knowledge 库
            return []

        alternatives: list[ChainAlternative] = []
        for cid in list_chains(base_dir=base_dir):
            try:
                chain = load_chain(cid, base_dir=base_dir)
            except Exception:  # noqa: BLE001 - 单链损坏跳过
                continue
            stage = chain.get("current_stage") or "阶段0-观察"
            if stage == "阶段0-观察":
                continue
            mappings = chain.get("mappings") or []
            pumped_seg = None
            for m in mappings:
                if str(m.get("code") or "").zfill(6) == code6:
                    pumped_seg = m.get("segment")
                    break
            if pumped_seg is None:
                continue
            seg_names = {s.get("id"): s.get("name")
                         for s in chain.get("segments") or []}
            for m in mappings:
                if m.get("segment") == pumped_seg:
                    continue
                c6 = str(m.get("code") or "").zfill(6)
                name = str(m.get("name") or "")
                if len(c6) != 6 or not name:
                    continue
                code_full = c6 + (".SH" if c6.startswith(("6", "9")) else ".SZ")
                seg_name = seg_names.get(m.get("segment")) or str(m.get("segment"))
                alternatives.append(
                    ChainAlternative(
                        code=code_full,
                        name=name,
                        chain_position=str(m.get("segment") or ""),
                        segment=seg_name,
                        reason=(
                            f"{pumped_stock} 所在环节已涨，推荐同链"
                            f"（{chain.get('name')}，{stage}）{seg_name}的标的"
                        ),
                    )
                )
        return alternatives
