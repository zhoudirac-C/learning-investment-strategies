import pytest

from qing_investment.agent.tools.daily_state import (
    _cleanup_opportunities,
    normalize_code,
    update_field,
)


class TestNormalizeCode:
    def test_sz_code(self):
        assert normalize_code("002409") == "002409.SZ"
        assert normalize_code("002409.SZ") == "002409.SZ"
        assert normalize_code("sz002409") == "002409.SZ"

    def test_sh_code(self):
        assert normalize_code("600246") == "600246.SH"
        assert normalize_code("600246.SH") == "600246.SH"
        assert normalize_code("sh600246") == "600246.SH"

    def test_empty(self):
        assert normalize_code("") == ""
        assert normalize_code(None) == ""


class TestUpdateField:
    def test_records_source(self):
        state = {}
        update_field(state, "market_summary:open_auction", "market_stage", {"phase": "test"})
        assert state["market_stage"]["phase"] == "test"
        assert state["_field_sources"]["market_stage"] == "market_summary:open_auction"


class TestCleanupOpportunities:
    def test_keeps_recent_invalid(self):
        from datetime import datetime, timedelta

        now = datetime.now()
        opportunities = [
            {
                "code": "000001.SZ",
                "status": "失效",
                "last_checked_at": (now - timedelta(days=1)).isoformat(),
            }
        ]
        assert len(_cleanup_opportunities(opportunities)) == 1

    def test_removes_old_invalid(self):
        from datetime import datetime, timedelta

        now = datetime.now()
        opportunities = [
            {
                "code": "000001.SZ",
                "status": "失效",
                "last_checked_at": (now - timedelta(days=5)).isoformat(),
            }
        ]
        assert len(_cleanup_opportunities(opportunities)) == 0

    def test_keeps_active(self):
        opportunities = [{"code": "000001.SZ", "status": "未触发"}]
        assert len(_cleanup_opportunities(opportunities)) == 1


from qing_investment.agent.tools.daily_state import add_opportunity, load_daily_state, save_daily_state


class TestAddOpportunity:
    def test_normalizes_code(self):
        state = add_opportunity(
            {}, "万通发展", "600246", "技术支撑", "回踩",
            upside="15%", downside="5%", ratio="3:1"
        )
        assert state["active_opportunities"][0]["code"] == "600246.SH"

    def test_preserves_first_seen_at(self):
        state = add_opportunity(
            {}, "万通发展", "600246", "技术支撑", "回踩",
            upside="15%", downside="5%", ratio="3:1"
        )
        first_seen = state["active_opportunities"][0]["first_seen_at"]
        state = add_opportunity(
            state, "万通发展", "600246", "技术支撑", "回踩",
            upside="16%", downside="5%", ratio="3.2:1"
        )
        opp = state["active_opportunities"][0]
        assert opp["first_seen_at"] == first_seen
        assert opp["upside"] == "16%"

    def test_schema_fields(self):
        state = add_opportunity(
            {}, "万通发展", "600246", "技术支撑", "回踩",
            upside="15%", downside="5%", ratio="3:1",
            entry_zone=[18.0, 19.0], stop_loss=17.5, source_node="stock_scanner"
        )
        opp = state["active_opportunities"][0]
        assert opp["entry_zone"] == [18.0, 19.0]
        assert opp["stop_loss"] == 17.5
        assert opp["source_node"] == "stock_scanner"


class TestSaveDailyStateCleanup:
    def test_save_cleans_old_invalid(self, tmp_path):
        from datetime import datetime, timedelta

        state_path = tmp_path / "daily_state.json"
        now = datetime.now()
        state = {
            "date": now.strftime("%Y-%m-%d"),
            "active_opportunities": [
                {"code": "000001.SZ", "status": "失效", "last_checked_at": (now - timedelta(days=5)).isoformat()},
                {"code": "000002.SZ", "status": "未触发"},
            ],
        }
        save_daily_state(state, state_path)
        loaded = load_daily_state(state_path)
        assert len(loaded["active_opportunities"]) == 1
        assert loaded["active_opportunities"][0]["code"] == "000002.SZ"
