"""merge_scanner_results 类型护栏测试（2026-10-13 服务崩溃事故）。

事故：10-13 10:34 LLM 把 opportunity_scan 返回成 dict 而非 list，
沿 scan_result → market_summary_ctx 传入 merge，`merged["opportunity_scan"].append`
炸 AttributeError 导致 Agent 进程退出，14:30 监控被迫降级。

护栏口径：opportunity_scan / position_plans 非 list 一律按 [] 处理（类型不符的
LLM 输出不可信，丢弃好过崩溃）；merge 永不因类型问题抛异常。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qing_investment.agent.graph.nodes import merge_scanner_results  # noqa: E402


def _shard(opp_scan, pos_plans=None):
    return {
        "market_context": {
            "opportunity_scan": opp_scan,
            "position_plans": pos_plans or [],
        },
        "reasoning_steps": [],
        "cost_tracking": [],
    }


class TestMergeTypeGuard:
    def test_summary_ctx_dict_opportunity_scan_no_crash(self):
        """market_summary_context 里 opportunity_scan 是 dict（LLM 对象输出）→ 不崩，按空表。"""
        state = {
            "stock_scanner_results": [_shard([{"code": "600636"}])],
            "market_summary_context": {"opportunity_scan": {"items": []}},
            "parsed_intent": {"analysis_type": "stock"},
            "trigger": {"id": "t1"},
        }
        out = merge_scanner_results(state)
        mc = out["market_context"]
        assert isinstance(mc["opportunity_scan"], list)
        assert mc["opportunity_scan"] == [{"code": "600636"}]

    def test_shard_dict_opportunity_scan_no_crash(self):
        """分片 market_context 的 opportunity_scan 是 dict → 该分片按空表，不崩。"""
        state = {
            "stock_scanner_results": [
                _shard({"a": 1}),
                _shard([{"code": "000001"}]),
            ],
            "market_summary_context": {},
            "parsed_intent": {"analysis_type": "stock"},
            "trigger": {"id": "t2"},
        }
        out = merge_scanner_results(state)
        assert out["market_context"]["opportunity_scan"] == [{"code": "000001"}]

    def test_position_plans_dict_no_crash(self):
        state = {
            "stock_scanner_results": [_shard([], pos_plans={"p": 1})],
            "market_summary_context": {"position_plans": {"x": 2}},
            "parsed_intent": {"analysis_type": "stock"},
            "trigger": {"id": "t3"},
        }
        out = merge_scanner_results(state)
        assert isinstance(out["market_context"]["position_plans"], list)

    def test_normal_lists_unchanged(self):
        state = {
            "stock_scanner_results": [_shard([{"code": "600636"}], [{"code": "000001"}])],
            "market_summary_context": {"opportunity_scan": [{"code": "300308"}]},
            "parsed_intent": {"analysis_type": "stock"},
            "trigger": {"id": "t4"},
        }
        out = merge_scanner_results(state)
        mc = out["market_context"]
        assert mc["opportunity_scan"] == [{"code": "300308"}, {"code": "600636"}]
        assert mc["position_plans"] == [{"code": "000001"}]
