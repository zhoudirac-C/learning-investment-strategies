"""Qing-Agent 监控引擎 — 门控层 (Phase 2)

Layer 1: MarketGate  — 今天是否适合开新仓？
Layer 2: SectorGate   — 该方向是否处于可介入阶段？
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from zoneinfo import ZoneInfo


CN_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class GateResult:
    """门控判断结果。"""

    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    reason: str = ""
    bias: str = "观望"  # 可操作 / 谨慎 / 观望


class MarketGate:
    """市场门控 — 判断今天是否适合开新仓。"""

    VOLUME_THRESHOLD = 2_500_000_000_000.0  # 2.5万亿

    def evaluate(self, config: dict, quote_snapshot: dict) -> GateResult:
        market_data = self._extract_market_data(quote_snapshot)
        rules = (config.get("strategy_pack", {}).get("market_gate_rules", {}) or {})

        checks: dict[str, bool] = {
            "全A非破位": self._check_index_ok(rules, market_data),
            "量能达标": self._check_volume(rules, market_data),
            "非连续恐慌": self._check_not_panicking(market_data),
            "非防守日": self._check_not_defense_day(config, market_data),
        }
        passed = sum(1 for v in checks.values() if v) >= 3
        bias = "可操作" if passed else "观望"
        return GateResult(
            passed=passed,
            checks=checks,
            bias=bias,
            reason="通过" if passed else "市场门控未通过",
        )

    def _extract_market_data(self, quote_snapshot: dict) -> dict:
        """从行情快照提取指数/市场数据。"""
        quotes = {}
        for q in (quote_snapshot or {}).get("quotes", []) or []:
            for key in (q.get("label"), q.get("name"), q.get("code")):
                if key:
                    quotes[str(key)] = q

        all_share = quotes.get("全A指数") or quotes.get("000985") or {}
        sh_index = quotes.get("上证指数") or quotes.get("000001") or {}

        total_amount = 0.0
        for q in (quote_snapshot or {}).get("quotes", []) or []:
            amt = q.get("amount")
            if isinstance(amt, (int, float)):
                total_amount += amt

        return {
            "all_share_latest": all_share.get("latest"),
            "all_share_pct": all_share.get("pct_change"),
            "sh_index_latest": sh_index.get("latest"),
            "sh_index_pct": sh_index.get("pct_change"),
            "total_amount": total_amount,
        }

    def _check_index_ok(self, rules: dict, market_data: dict) -> bool:
        """检查指数是否破位。"""
        for check in rules.get("index_checks", []):
            idx_name = check.get("index", "")
            level = check.get("level")
            cond = check.get("condition", "")
            if level is None or not cond:
                continue
            latest = market_data.get("all_share_latest") if "全A" in idx_name else market_data.get("sh_index_latest")
            if latest is None:
                continue
            if cond == "not_close_below" and float(latest) <= level:
                return False
        return True

    def _check_volume(self, rules: dict, market_data: dict) -> bool:
        """检查量能是否达标。"""
        volume_checks = rules.get("volume_checks", [])
        if not volume_checks:
            return market_data.get("total_amount", 0) >= self.VOLUME_THRESHOLD
        for check in volume_checks:
            metric = check.get("metric", "total_amount")
            threshold = check.get("threshold", self.VOLUME_THRESHOLD)
            if metric == "total_amount":
                total = market_data.get("total_amount", 0)
                if isinstance(total, str):
                    total = float(total)
                if isinstance(threshold, str):
                    threshold = float(threshold)
                if total >= threshold:
                    return True
        return False

    def _check_not_panicking(self, market_data: dict) -> bool:
        """检查是否非连续恐慌（简化：指数跌幅<3%）。"""
        pct = market_data.get("all_share_pct") or market_data.get("sh_index_pct")
        if pct is None:
            return True
        return pct > -3.0

    def _check_not_defense_day(self, config: dict, market_data: dict) -> bool:
        """检查是否为防守日。当前为简化实现：银行保险领涨由 LLM/上层判断，这里恒 true。"""
        # P2 阶段先用规则占位，后续接入 sector_rotation 结果。
        return True


class SectorGate:
    """板块门控 — 判断该方向是否处于可介入阶段。"""

    STAGE_ACTIONABLE = {"early_direction", "diverging", "resuming"}
    STAGE_SKIP = {"first_pump", "ending"}

    def evaluate(self, direction: dict, sector_data: dict | None = None) -> GateResult:
        stage = direction.get("current_stage", "")

        if stage in self.STAGE_SKIP:
            return GateResult(
                passed=False,
                reason=f"板块处于 {stage}，跳过该方向所有标的",
                bias="观望",
            )
        if stage in self.STAGE_ACTIONABLE:
            return GateResult(
                passed=True,
                reason=f"板块处于 {stage}，可寻找低位标的",
                bias="可操作",
            )
        return GateResult(
            passed=False,
            reason=f"板块阶段未知 ({stage})，暂不介入",
            bias="观望",
        )
