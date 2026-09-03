"""回归测试：测试套件运行期间不得写入生产 daily_state.json。

背景（2026-08-31 事故）：tests/test_qing_agent_monitor_workflow.py 的
全图测试未隔离 daily_state 持久化，FakeLLM 的 canned 输出
（"磨底期" / "mock reasoning" / 假机会 000021.SZ）经 market_summary 与
merge_scanner_results 节点写入生产文件 config/stock_monitor/daily_state.json，
污染当日收盘复盘，并会被次日「昨日特征摘要」继承。

修复：tests/conftest.py 的 autouse fixture 将
qing_investment.agent.tools.daily_state.DEFAULT_STATE_PATH 重定向到
每个测试独立的 tmp_path。本测试守护该安全网不被移除。
"""

from __future__ import annotations

import json
from pathlib import Path

from qing_investment.agent.tools import daily_state as ds
from qing_investment.paths import repo_root

_PROD_STATE_PATH = repo_root() / "config" / "stock_monitor" / "daily_state.json"


def test_default_state_path_isolated_from_production():
    """测试进程中 DEFAULT_STATE_PATH 必须指向仓库之外的隔离路径。"""
    resolved = Path(ds.DEFAULT_STATE_PATH).resolve()
    assert resolved != _PROD_STATE_PATH.resolve()
    assert repo_root() not in resolved.parents


def test_unpatched_merge_persists_only_to_isolated_path():
    """不 patch 持久化函数跑 merge_scanner_results：写入只落在隔离路径。"""
    from qing_investment.agent.graph.nodes import merge_scanner_results

    state = {
        "stock_scanner_results": [],
        "market_summary_context": {
            "market_phase": "回暖期",
            "phase_reasoning": "isolation test",
            "main_themes": ["测试方向"],
        },
        "trigger": {"id": "morning_confirm"},
        "parsed_intent": {"analysis_type": "market"},
    }
    merge_scanner_results(state)

    isolated = Path(ds.DEFAULT_STATE_PATH)
    assert isolated.exists()
    data = json.loads(isolated.read_text(encoding="utf-8"))
    assert data["market_stage"]["phase"] == "回暖期"
    assert data["direction_priority"][0]["direction"] == "测试方向"
