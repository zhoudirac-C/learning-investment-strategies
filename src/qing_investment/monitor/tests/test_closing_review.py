"""收盘复盘闭环测试 — Phase 1

覆盖：
  - 17:00 closing_review 节点被正确调度
  - trigger 携带 closing_review id
  - market_summary 节点根据 trigger.id 选择 cron_closing.txt prompt
  - daily_state 版本化追加写入
  - 收盘复盘后 daily_state 归档
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_CN_TZ = ZoneInfo("Asia/Shanghai")


class SimpleConfig:
    """最小配置对象，兼容 scheduler 函数签名。"""

    def __init__(self, strategy_pack: dict):
        self.strategy_pack = strategy_pack


class TestClosingReviewSchedule:
    """17:00 收盘复盘调度测试。"""

    def test_agent_schedule_detects_closing_review_at_1700(self):
        from qing_investment.monitor.scheduler import AgentSchedule

        strategy_pack = {
            "agent_analysis_schedule": [
                {"id": "tail_condition", "time": "14:52", "name": "尾盘条件单", "focus": "..."},
                {"id": "closing_review", "time": "17:00", "name": "收盘复盘", "focus": "全天复盘与明日假设"},
            ]
        }
        schedule = AgentSchedule.from_config(strategy_pack)

        value = datetime(2026, 7, 10, 17, 0, tzinfo=_CN_TZ)
        assert schedule.is_scheduled_time(value) is True

    def test_find_agent_analysis_trigger_returns_closing_review_id(self):
        from qing_investment.monitor.scheduler import find_agent_analysis_trigger

        config = SimpleConfig(
            strategy_pack={
                "agent_analysis_schedule": [
                    {"id": "closing_review", "time": "17:00", "name": "收盘复盘", "focus": "全天复盘与明日假设"},
                ]
            }
        )
        state = {"agent_analysis_history": {}}
        value = datetime(2026, 7, 10, 17, 0, tzinfo=_CN_TZ)

        trigger = find_agent_analysis_trigger(config, state, value, alerts=[])

        assert trigger is not None
        assert trigger.id == "closing_review"
        assert trigger.title == "收盘复盘"
        assert "全天复盘" in trigger.reason

    def test_closing_review_not_triggered_at_other_times(self):
        from qing_investment.monitor.scheduler import find_agent_analysis_trigger

        config = SimpleConfig(
            strategy_pack={
                "agent_analysis_schedule": [
                    {"id": "closing_review", "time": "17:00", "name": "收盘复盘", "focus": "全天复盘与明日假设"},
                ]
            }
        )
        state = {"agent_analysis_history": {}}
        value = datetime(2026, 7, 10, 16, 59, tzinfo=_CN_TZ)

        trigger = find_agent_analysis_trigger(config, state, value, alerts=[])
        assert trigger is None


class TestDailyStateVersioning:
    """daily_state 版本化/追加写入测试。"""

    def test_intraday_narrative_appends_multiple_entries(self):
        from qing_investment.agent.tools.daily_state import (
            _init_daily_state,
            add_intraday_narrative,
        )

        state = _init_daily_state()
        state = add_intraday_narrative(state, "09:30 节点分析", "早盘缩量冰点")
        state = add_intraday_narrative(state, "10:00 节点分析", "科技主线确认")
        state = add_intraday_narrative(state, "15:00 节点分析", "收盘缩量十字星")

        assert len(state["intraday_narrative"]) == 3
        assert state["intraday_narrative"][0]["summary"] == "早盘缩量冰点"
        assert state["intraday_narrative"][-1]["summary"] == "收盘缩量十字星"

    def test_add_opportunity_preserves_history(self):
        from qing_investment.agent.tools.daily_state import (
            _init_daily_state,
            add_opportunity,
        )

        state = _init_daily_state()
        state = add_opportunity(state, "北方华创", "002371", "龙头分歧低吸", "回踩5日线", "10%", "-4%", "2.5:1")
        first_updated_at = state["active_opportunities"][0]["updated_at"]

        # 同一标的新状态写入应更新而非重复追加
        state = add_opportunity(state, "北方华创", "002371", "龙头分歧低吸", "回踩10日线", "12%", "-3%", "4:1")
        assert len(state["active_opportunities"]) == 1
        assert state["active_opportunities"][0]["trigger"] == "回踩10日线"
        assert state["active_opportunities"][0]["updated_at"] != first_updated_at


class TestDailyStateArchive:
    """收盘复盘后 daily_state 归档测试。"""

    def test_archive_daily_state_creates_history_file(self):
        from qing_investment.agent.tools.daily_state import archive_daily_state, save_daily_state, _init_daily_state

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "daily_state.json"
            state = _init_daily_state()
            state["date"] = "2026-07-10"
            save_daily_state(state, path)

            archive_path = archive_daily_state(path)

            assert archive_path is not None
            assert archive_path.exists()
            assert archive_path.name == "daily_state_2026-07-10.json"
            archived = json.loads(archive_path.read_text(encoding="utf-8"))
            assert archived["date"] == "2026-07-10"

    def test_market_summary_archives_daily_state_on_closing_review(self, monkeypatch, tmp_path):
        """收盘复盘节点执行后应归档 daily_state。"""
        import qing_investment.agent.graph.nodes as nodes
        from qing_investment.agent.graph.nodes import market_summary

        monkeypatch.setattr(nodes, "_safe_llm_invoke", lambda prompt, min_length=0, use_acp_first=None: json.dumps({"market_phase": "test"}))
        monkeypatch.setattr(nodes, "_load_reasoning_patterns", lambda state: [])

        archive_calls: list[Path | None] = []

        def _fake_archive(path=None):
            archive_calls.append(path)
            return None

        monkeypatch.setattr("qing_investment.agent.graph.nodes.archive_daily_state", _fake_archive)

        state = {
            "query": "收盘复盘",
            "parsed_intent": {"analysis_type": "market", "stock_code": ""},
            "trigger": {"id": "closing_review", "title": "收盘复盘", "reason": "全天复盘"},
            "claims": [],
            "wiki_snippets": [],
            "sector_context": [],
            "memories": [],
            "few_shot_examples": [],
            "market_snapshot": {"quotes": []},
            "external_sector_boards": {},
        }

        market_summary(state)

        assert len(archive_calls) == 1


class TestMarketSummaryPromptSelection:
    """market_summary 节点根据 trigger.id 选择 prompt 测试。"""

    def test_market_summary_selects_cron_closing_prompt_for_closing_review(self):
        from qing_investment.agent.graph.nodes import _load_prompt_for_trigger

        prompt = _load_prompt_for_trigger(trigger_id="closing_review", default_name="market_summary")

        assert "收盘复盘" in prompt
        assert "daily_state" in prompt

    def test_market_summary_uses_closing_prompt_when_trigger_id_is_closing_review(self, monkeypatch):
        """market_summary 在 trigger.id=closing_review 时传入 cron_closing prompt。"""
        import qing_investment.agent.graph.nodes as nodes
        from qing_investment.agent.graph.nodes import market_summary

        captured_prompts: list[str] = []

        def _fake_invoke(prompt: str, min_length: int = 0, use_acp_first=None):
            captured_prompts.append(prompt)
            # 返回一个合法但最小的 daily_state 块，避免后续解析失败
            return json.dumps({"market_phase": "缩量冰点", "market_summary": "test"}) + (
                '\n```daily_state\n{"market_stage":{"phase":"test"}}\n```'
            )

        monkeypatch.setattr(nodes, "_safe_llm_invoke", _fake_invoke)
        monkeypatch.setattr(nodes, "_load_reasoning_patterns", lambda state: [])

        state = {
            "query": "收盘复盘",
            "parsed_intent": {"analysis_type": "market", "stock_code": ""},
            "trigger": {"id": "closing_review", "title": "收盘复盘", "reason": "全天复盘"},
            "claims": [],
            "wiki_snippets": [],
            "sector_context": [],
            "memories": [],
            "few_shot_examples": [],
            "market_snapshot": {"quotes": []},
            "external_sector_boards": {},
        }

        result = market_summary(state)

        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "收盘复盘" in prompt
        assert "daily_state_summary" in prompt
        assert result.get("market_summary_context", {}).get("market_phase") == "缩量冰点"

    def test_closing_prompt_includes_daily_state_history(self, monkeypatch):
        """收盘复盘 prompt 的 daily_state_summary 包含 history 演进。"""
        import qing_investment.agent.graph.nodes as nodes
        from qing_investment.agent.graph.nodes import market_summary

        captured_prompts: list[str] = []

        def _fake_invoke(prompt: str, min_length: int = 0, use_acp_first=None):
            captured_prompts.append(prompt)
            return json.dumps({"market_phase": "缩量冰点", "market_summary": "test"})

        monkeypatch.setattr(nodes, "_safe_llm_invoke", _fake_invoke)
        monkeypatch.setattr(nodes, "_load_reasoning_patterns", lambda state: [])

        # 构造一个带 history 的 daily_state
        fake_state = {
            "date": "2026-07-10",
            "market_stage": {"phase": "回暖期", "detail": "放量", "updated_by": "ms", "updated_at": "t2"},
            "direction_priority": [{"direction": "半导体", "intensity": "🔥🔥🔥"}],
            "position_stance": "轻仓",
            "active_opportunities": [{"stock": "A", "code": "000001", "pattern": "test", "status": "未触发"}],
            "intraday_narrative": [{"time": "09:30", "summary": "冰点", "timestamp": "t1"}],
            "history": [
                {
                    "version": 1,
                    "source": "market_summary:market",
                    "timestamp": "2026-07-10T09:30:00",
                    "market_stage": {"phase": "冰点期"},
                    "direction_priority": [{"direction": "半导体"}],
                    "position_stance": "空仓",
                    "opportunity_count": 0,
                    "narrative_count": 0,
                }
            ],
        }
        monkeypatch.setattr(nodes, "load_daily_state", lambda: fake_state)

        state = {
            "query": "收盘复盘",
            "parsed_intent": {"analysis_type": "market", "stock_code": ""},
            "trigger": {"id": "closing_review", "title": "收盘复盘", "reason": "全天复盘"},
            "claims": [],
            "wiki_snippets": [],
            "sector_context": [],
            "memories": [],
            "few_shot_examples": [],
            "market_snapshot": {"quotes": []},
            "external_sector_boards": {},
        }

        market_summary(state)

        prompt = captured_prompts[0]
        assert "今日关键判断演进" in prompt
        assert "冰点期" in prompt
        assert "回暖期" in prompt

    def test_market_summary_uses_default_prompt_without_trigger(self, monkeypatch):
        """无 trigger 时 market_summary 使用默认 market_summary prompt。"""
        import qing_investment.agent.graph.nodes as nodes
        from qing_investment.agent.graph.nodes import market_summary

        captured_prompts: list[str] = []

        def _fake_invoke(prompt: str, min_length: int = 0, use_acp_first=None):
            captured_prompts.append(prompt)
            return json.dumps({"market_phase": "磨底期", "market_summary": "test"})

        monkeypatch.setattr(nodes, "_safe_llm_invoke", _fake_invoke)
        monkeypatch.setattr(nodes, "_load_reasoning_patterns", lambda state: [])

        state = {
            "query": "市场分析",
            "parsed_intent": {"analysis_type": "market", "stock_code": ""},
            "trigger": None,
            "claims": [],
            "wiki_snippets": [],
            "sector_context": [],
            "memories": [],
            "few_shot_examples": [],
            "market_snapshot": {"quotes": []},
            "external_sector_boards": {},
        }

        market_summary(state)

        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        # 默认 market_summary prompt 不含 "收盘复盘" 标题
        assert "【17:00 收盘复盘" not in prompt


class TestDailyStateVersionedPersist:
    """daily_state 版本化持久化测试。"""

    def test_persist_appends_narrative_and_increments_version(self, monkeypatch):
        from qing_investment.agent.graph.nodes import _persist_daily_state_from_market_context
        from qing_investment.agent.tools.daily_state import _init_daily_state

        import copy

        savedStates: list[dict] = [_init_daily_state()]

        def _fake_load():
            return copy.deepcopy(savedStates[-1])

        def _fake_save(state):
            savedStates.append(copy.deepcopy(state))

        monkeypatch.setattr("qing_investment.agent.graph.nodes.load_daily_state", _fake_load)
        monkeypatch.setattr("qing_investment.agent.graph.nodes.save_daily_state", _fake_save)

        _persist_daily_state_from_market_context(
            market_context={"market_summary": "早盘缩量冰点"},
            daily_state_override={"market_stage": {"phase": "冰点期", "detail": "缩量"}},
            source_tag="market_summary:09:30",
        )
        _persist_daily_state_from_market_context(
            market_context={"market_summary": "午后科技主线确认"},
            daily_state_override={"market_stage": {"phase": "回暖期", "detail": "放量"}},
            source_tag="market_summary:14:00",
        )

        assert len(savedStates) == 3  # 初始 + 两次保存
        first_saved = savedStates[1]
        final = savedStates[-1]
        # narrative 追加
        assert len(final["intraday_narrative"]) == 2
        # 版本号递增（初始 version=1，两次保存后应为 3）
        assert first_saved["version"] == 2
        assert final["version"] == 3
        # history 记录两次变更
        assert len(final["history"]) == 2
        # _meta 记录最后更新
        assert final["_meta"]["last_persisted_by"] == "market_summary:14:00"
        # 当前 market_stage 为最后一次写入
        assert final["market_stage"]["phase"] == "回暖期"

    def test_persist_from_stock_scanner_does_not_increment_version_or_history(self, monkeypatch):
        """stock_scanner 调用持久化时不应递增 version 或填充 history。"""
        from qing_investment.agent.graph.nodes import _persist_daily_state_from_market_context
        from qing_investment.agent.tools.daily_state import _init_daily_state

        import copy

        savedStates: list[dict] = [_init_daily_state()]

        def _fake_load():
            return copy.deepcopy(savedStates[-1])

        def _fake_save(state):
            savedStates.append(copy.deepcopy(state))

        monkeypatch.setattr("qing_investment.agent.graph.nodes.load_daily_state", _fake_load)
        monkeypatch.setattr("qing_investment.agent.graph.nodes.save_daily_state", _fake_save)

        _persist_daily_state_from_market_context(
            market_context={"market_summary": "早盘缩量冰点"},
            daily_state_override={"market_stage": {"phase": "冰点期", "detail": "缩量"}},
            source_tag="market_summary:market",
        )
        _persist_daily_state_from_market_context(
            market_context={"opportunity_scan": [{"stock": "A", "code": "000001", "pattern": "test", "status": "未触发"}]},
            daily_state_override={"active_opportunities": [{"stock": "A", "code": "000001", "pattern": "test", "status": "未触发"}]},
            source_tag="stock_scanner:market",
        )

        final = savedStates[-1]
        # market_summary 第一次保存后 version=2；stock_scanner 不应再递增
        assert final["version"] == 2
        # history 只应记录 market_summary 节点
        assert len(final["history"]) == 1
        assert final["history"][0]["source"].startswith("market_summary")
        # 但 stock_scanner 带来的机会应被保留
        assert len(final["active_opportunities"]) == 1
        assert final["active_opportunities"][0]["code"] == "000001"
