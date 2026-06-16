"""买入信号检测系统端到端测试。

验证完整链路：
1. evaluate_buy_signal_candidates() 生成候选
2. evaluate_buy_signal_alerts() 转换为 alert
3. find_agent_analysis_trigger() 检测候选并生成 trigger
4. format_agent_json_context() 构建 JSON payload（含 analysis_type="stock"）
5. Agent 端接收 payload 并路由到 stock_analyst 节点
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from qing_investment.stock_monitor import (
    BuySignalCandidate,
    MonitorConfig,
    RuleAlert,
    evaluate_buy_signal_alerts,
    evaluate_buy_signal_candidates,
    find_agent_analysis_trigger,
    find_any_agent_analysis_trigger,
    format_agent_json_context,
)


class TestBuySignalE2E:
    """端到端测试：从候选检测到 Agent payload 构建。"""

    def _make_config(self) -> MonitorConfig:
        """构造最小化的测试配置。"""
        return MonitorConfig(
            config_dir=Path("/tmp"),
            positions_path=Path("/tmp/positions.yaml"),
            watchlist={
                "themes": [
                    {
                        "name": "测试主题",
                        "stocks": [
                            {
                                "code": "000001",
                                "name": "平安银行",
                                "buy_setup": "10.0-11.0",
                                "invalidation_setup": "9.5",
                                "pre_condition": {
                                    "market_actionable": True,
                                    "sector_diverged": True,
                                    "market_gate_note": "测试大盘备注",
                                },
                            }
                        ],
                    }
                ]
            },
            positions={"accounts": []},
            strategy_pack={
                "market_framework": {
                    "current_stage": "回暖期",
                    "core_question": "测试",
                },
                "entry_points": [
                    {
                        "code": "000001",
                        "name": "平安银行",
                        "entry_zone": "10.0-11.0",
                        "stop_loss": 9.5,
                        "claim_basis": "UP看好银行板块",
                        "odds_analysis": {"upside_pct": 15, "downside_pct": 5},
                    }
                ],
            },
            stock_pool={
                "stocks": [
                    {
                        "code": "000001",
                        "name": "平安银行",
                        "direction": "test_dir",
                        "entry": {"primary_zone": [10.0, 11.0]},
                        "pre_condition": {
                            "sector_diverged": True,
                            "market_actionable": True,
                        },
                    }
                ]
            },
        )

    def _make_quote_snapshot(self, price: float = 10.5, pct_change: float = 1.5) -> dict:
        return {
            "source": "test",
            "elapsed_ms": 100,
            "quotes": [
                {
                    "code": "000001",
                    "name": "平安银行",
                    "latest": price,
                    "pct_change": pct_change,
                }
            ],
        }

    def test_evaluate_buy_signal_candidates_detects_opportunity(self):
        """候选检测：价格进入区间 + 满足 >=4/6 条件。"""
        config = self._make_config()
        snapshot = self._make_quote_snapshot(price=10.5, pct_change=1.5)

        candidates = evaluate_buy_signal_candidates(config, snapshot)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.stock_code == "000001"
        assert c.is_candidate is True
        assert len(c.matched_conditions) >= 5
        assert "价格进入区间" in c.matched_conditions
        assert "板块分歧" in c.matched_conditions
        assert "大盘可操作" in c.matched_conditions
        assert c.entry_zone == (10.0, 11.0)

    def test_evaluate_buy_signal_candidates_rejects_when_price_out_of_zone(self):
        """候选检测：价格不在区间内 → 不是候选。"""
        config = self._make_config()
        # 显式关闭前置条件，确保价格不在区间时总满足条件 < 5
        config.stock_pool = {
            "stocks": [
                {
                    "code": "000001",
                    "pre_condition": {
                        "sector_diverged": False,
                        "market_actionable": False,
                    },
                }
            ]
        }
        snapshot = self._make_quote_snapshot(price=12.0, pct_change=1.5)

        candidates = evaluate_buy_signal_candidates(config, snapshot)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.is_candidate is False
        assert "价格进入区间" not in c.matched_conditions

    def test_evaluate_buy_signal_alerts_generates_opportunity_alert(self):
        """Alert 转换：候选生成 RuleAlert（action="机会候选"）。"""
        config = self._make_config()
        snapshot = self._make_quote_snapshot(price=10.5)

        alerts = evaluate_buy_signal_alerts(config, snapshot)

        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.action == "机会候选"
        assert alert.stock_code == "000001"
        assert alert.severity == "opportunity"
        assert "进入介入区间" in alert.trigger

    def test_find_agent_analysis_trigger_detects_buy_candidate(self):
        """Trigger 检测：买入候选 alert → kind="buy_signal_candidate"。"""
        config = self._make_config()
        snapshot = self._make_quote_snapshot(price=10.5)
        alerts = evaluate_buy_signal_alerts(config, snapshot)
        state = {}
        value = datetime(2026, 6, 11, 10, 0, 0, tzinfo=timezone(timedelta(hours=8)))

        trigger = find_agent_analysis_trigger(config, state, value, alerts)

        assert trigger is not None
        assert trigger.kind == "buy_signal_candidate"
        assert "000001" in trigger.reason
        assert "满足买入条件" in trigger.reason

    def test_find_agent_analysis_trigger_dedupes_buy_candidate(self):
        """Trigger 去重：同一候选在 history 中已存在 → 不重复触发。"""
        config = self._make_config()
        snapshot = self._make_quote_snapshot(price=10.5)
        alerts = evaluate_buy_signal_alerts(config, snapshot)
        state = {
            "agent_analysis_history": {
                "buy_candidate:2026-06-11:000001": {
                    "time": "2026-06-11T09:30:00+08:00",
                    "kind": "buy_signal_candidate",
                }
            }
        }
        value = datetime(2026, 6, 11, 10, 0, 0, tzinfo=timezone(timedelta(hours=8)))

        trigger = find_agent_analysis_trigger(config, state, value, alerts)

        assert trigger is None

    def test_json_context_contains_analysis_type_stock(self):
        """JSON payload：trigger.kind="buy_signal_candidate" → analysis_type="stock"。"""
        config = self._make_config()
        snapshot = self._make_quote_snapshot(price=10.5)
        alerts = evaluate_buy_signal_alerts(config, snapshot)
        value = datetime(2026, 6, 11, 10, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        trigger = find_agent_analysis_trigger(config, {}, value, alerts)
        assert trigger is not None

        state = {}
        json_str = format_agent_json_context(
            config, value, trigger, alerts, snapshot, state
        )
        data = json.loads(json_str)

        assert data["analysis_type"] == "stock"
        assert data["stock_code"] == "000001"
        assert data["trigger"]["kind"] == "buy_signal_candidate"
        assert len(data["buy_signal_candidates"]) == 1
        candidate = data["buy_signal_candidates"][0]
        assert candidate["stock_code"] == "000001"
        assert candidate["entry_zone"] == [10.0, 11.0]
        assert candidate.get("pre_condition") == "大盘可操作；板块首次分歧；备注：测试大盘备注"

    def test_json_context_fallback_to_market_for_regular_alert(self):
        """JSON payload：普通 alert → analysis_type="market"。"""
        config = self._make_config()
        snapshot = self._make_quote_snapshot(price=10.5)
        # 普通 alert（非买入候选）
        alerts = [
            RuleAlert(
                action="减仓观察",
                stock_code="000001",
                stock_name="平安银行",
                price=10.5,
                trigger="跌破支撑位",
                severity="warning",
                summary="测试预警",
            )
        ]
        value = datetime(2026, 6, 11, 10, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        trigger = find_agent_analysis_trigger(config, {}, value, alerts)
        assert trigger is not None

        state = {}
        json_str = format_agent_json_context(
            config, value, trigger, alerts, snapshot, state
        )
        data = json.loads(json_str)

        assert data["analysis_type"] == "market"
        assert data["stock_code"] == ""
        assert data["trigger"]["kind"] == "event"

    def test_find_any_agent_analysis_trigger_bypasses_time_restriction(self):
        """find_any：非交易时间也能检测买入候选（cron 用）。"""
        config = self._make_config()
        snapshot = self._make_quote_snapshot(price=10.5)
        alerts = evaluate_buy_signal_alerts(config, snapshot)
        # 非交易时间（15:30 后）
        value = datetime(2026, 6, 11, 16, 0, 0, tzinfo=timezone(timedelta(hours=8)))

        trigger = find_any_agent_analysis_trigger(config, {}, value, alerts)

        assert trigger is not None
        assert trigger.kind == "buy_signal_candidate"
