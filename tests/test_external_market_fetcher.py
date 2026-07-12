import pytest

from qing_investment.agent.tools import external_market_fetcher


class TestFetchPreMarketBrief:
    def test_structure(self, monkeypatch):
        """验证返回结构，所有数据源 mock 为简单字典。"""

        def mock_us():
            return {
                "indices": {"nasdaq": {"price": 1, "pct_change": 0.1}},
                "semi_index": {"price": 2},
                "tech_stocks": {"nvda": {"price": 3}},
            }

        def mock_asia():
            return {"indices": {"kospi": {"price": 1}, "nikkei": {"price": 2}}}

        def mock_futures():
            return {"a50": {"price": 1}, "crude": None, "gold": None, "dxy": None, "us10y": None, "risks": []}

        monkeypatch.setattr(external_market_fetcher, "_fetch_us_overnight", mock_us)
        monkeypatch.setattr(external_market_fetcher, "_fetch_asia_first_hour", mock_asia)
        monkeypatch.setattr(external_market_fetcher, "_fetch_futures_geopolitics", mock_futures)

        result = external_market_fetcher.fetch_pre_market_brief()
        # run async
        import asyncio

        result = asyncio.run(result)

        assert result["available"] is True
        assert "us_overnight" in result
        assert "asia_first_hour" in result
        assert "futures_geopolitics" in result
        assert "core_assumption" in result
        assert "key_risks" in result
