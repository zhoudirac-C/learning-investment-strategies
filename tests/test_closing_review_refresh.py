from qing_investment.agent.graph.nodes import _refresh_active_opportunity_statuses


class TestRefreshActiveOpportunityStatuses:
    def test_triggered_when_in_positions(self):
        ds = {
            "active_opportunities": [
                {"code": "600246.SH", "status": "候选", "entry_zone": [18.0, 19.0], "stop_loss": 17.5}
            ]
        }
        _refresh_active_opportunity_statuses(
            ds,
            positions=[{"code": "600246.SH", "shares": 100}],
            quotes=[{"code": "600246", "latest": 18.5}],
        )
        assert ds["active_opportunities"][0]["status"] == "已触发"

    def test_invalid_when_below_stop_loss(self):
        ds = {
            "active_opportunities": [
                {"code": "600246.SH", "status": "候选", "entry_zone": [18.0, 19.0], "stop_loss": 17.5}
            ]
        }
        _refresh_active_opportunity_statuses(
            ds,
            positions=[],
            quotes=[{"code": "600246", "latest": 17.0}],
        )
        assert ds["active_opportunities"][0]["status"] == "失效"

    def test_candidate_when_in_entry_zone(self):
        ds = {
            "active_opportunities": [
                {"code": "600246.SH", "status": "未触发", "entry_zone": [18.0, 19.0], "stop_loss": 17.5}
            ]
        }
        _refresh_active_opportunity_statuses(
            ds,
            positions=[],
            quotes=[{"code": "600246", "latest": 18.5}],
        )
        assert ds["active_opportunities"][0]["status"] == "候选"
