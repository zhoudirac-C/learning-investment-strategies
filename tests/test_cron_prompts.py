from pathlib import Path

import pytest

from qing_investment.agent.graph.nodes import _load_prompt_for_trigger, _persist_daily_state_from_market_context
from qing_investment.agent.tools.daily_state import load_daily_state
def _prompt_text(name: str) -> str:
    # 使用测试文件所在的工作区根目录（兼容 git worktree）
    path = Path(__file__).resolve().parents[1] / "src" / "qing_investment" / "agent" / "prompts" / "system" / f"{name}.txt"
    return path.read_text(encoding="utf-8")


class TestCronOpeningPrompt:
    def test_contains_scenario_validation(self):
        text = _prompt_text("cron_opening")
        assert "scenario_validation" in text
        assert "剧本验证" in text

    def test_contains_pre_market_placeholder(self):
        text = _prompt_text("cron_opening")
        assert "{pre_market_brief}" in text

    def test_no_long_early_session_analysis(self):
        text = _prompt_text("cron_opening")
        # 不应再强调大段“早盘定性”
        assert "早盘定性" not in text


class TestCronMorningConfirmPrompt:
    def test_contains_assumption_validation(self):
        text = _prompt_text("cron_morning_confirm")
        assert "assumption_validation" in text

    def test_contains_core_assumption_placeholder(self):
        text = _prompt_text("cron_morning_confirm")
        assert "{core_assumption_0926}" in text


class TestIntradayNarrativeLabels:
    def test_open_auction_label(self, tmp_path, monkeypatch):
        state_path = tmp_path / "daily_state.json"
        monkeypatch.setattr(
            "qing_investment.agent.tools.daily_state.DEFAULT_STATE_PATH", state_path
        )
        _persist_daily_state_from_market_context(
            {"market_summary": "test summary"},
            None,
            "market_summary:market",
            trigger_id="open_auction",
        )
        state = load_daily_state(state_path)
        narrative = state.get("intraday_narrative", [])
        assert narrative
        assert "09:26 剧本验证" in narrative[-1]["time"]

    def test_morning_confirm_label(self, tmp_path, monkeypatch):
        state_path = tmp_path / "daily_state.json"
        monkeypatch.setattr(
            "qing_investment.agent.tools.daily_state.DEFAULT_STATE_PATH", state_path
        )
        _persist_daily_state_from_market_context(
            {"market_summary": "test summary"},
            None,
            "market_summary:market",
            trigger_id="morning_confirm",
        )
        state = load_daily_state(state_path)
        narrative = state.get("intraday_narrative", [])
        assert narrative
        assert "10:00 结论固化" in narrative[-1]["time"]



class TestCronPreMarketPrompt:
    def test_prompt_exists_and_has_json_schema(self):
        text = _prompt_text("cron_pre_market")
        assert "us_overnight" in text
        assert "asia_first_hour" in text
        assert "futures_geopolitics" in text
        assert "pre_market_brief" in text

    def test_prompt_map(self):
        assert "pre_market_brief" in _load_prompt_for_trigger("pre_market", "market_summary")
        assert "scenario_validation" in _load_prompt_for_trigger("open_auction", "market_summary")
        assert "assumption_validation" in _load_prompt_for_trigger("morning_confirm", "market_summary")



class TestPreMarketSchedule:
    def test_yaml_contains_pre_market(self):
        import yaml

        pack_path = Path(__file__).resolve().parents[1] / "config" / "stock_monitor" / "strategy_pack.yaml"
        pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        ids = [row.get("id") for row in pack.get("agent_analysis_schedule", []) if isinstance(row, dict)]
        assert "pre_market" in ids


class TestQingRealtimeAnchorRemoval:
    @pytest.mark.parametrize(
        "name",
        [
            "trader_mindset",
            "market_summary",
            "stock_analyst",
            "stock_scanner",
            "reviewer",
            "market_analyst",
        ],
    )
    def test_prompts_have_no_qing_current_priority_rules(self, name):
        text = _prompt_text(name)
        for forbidden in (
            "UP当前最看好",
            "UP 当前最看好",
            "UP周期判断优先",
            "UP个股定位优先",
            "优先于LLM自主周期判断",
            "如果 UP 最近已经转中性/谨慎",
        ):
            assert forbidden not in text

    @pytest.mark.parametrize(
        "name",
        ["market_summary", "stock_analyst", "stock_scanner", "market_analyst"],
    )
    def test_qing_direction_signal_projection_is_not_documented_as_input(self, name):
        assert "direction_signals" not in _prompt_text(name)

    def test_legacy_market_prompt_does_not_use_up_sentiment(self):
        assert "up_sentiment" not in _prompt_text("market_analyst")

    def test_reviewer_does_not_enforce_alignment_with_qing_history(self):
        text = _prompt_text("reviewer")
        assert "是否与UP的历史立场矛盾" not in text
        assert "历史" in text
        assert "当前信号" in text

    def test_chat_inline_prompt_treats_qing_views_as_history(self):
        main_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "qing_investment"
            / "agent"
            / "main.py"
        )
        text = main_path.read_text(encoding="utf-8")
        for forbidden in (
            "【UP最新观点】",
            "【UP近期观点】",
            "【UP周期判断优先】",
            "【UP个股定位优先】",
            "优先使用【UP最新观点】",
        ):
            assert forbidden not in text
        assert "【Qing历史观点】" in text
