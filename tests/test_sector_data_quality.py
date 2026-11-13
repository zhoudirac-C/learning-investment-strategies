from __future__ import annotations

import urllib.error
from dataclasses import asdict
from unittest.mock import Mock

import pytest

from qing_investment.agent.tools import sector_data
from qing_investment.agent.tools.sector_data import SectorBoardItem


def _item(
    *,
    pct_change: object = 0.0,
    latest: object = 0.0,
    amount: object = 0.0,
) -> SectorBoardItem:
    return SectorBoardItem(
        code="BK0001",
        name="测试板块",
        pct_change=pct_change,
        latest=latest,
        amount=amount,
        rank=1,
        board_type="concept",
    )


def _failed_provider(*args, **kwargs):
    raise urllib.error.URLError("provider unavailable")


def _patch_failed_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "fetch_eastmoney_boards",
        "fetch_sina_boards",
        "fetch_tdx_boards",
        "fetch_ths_change_boards",
    ):
        monkeypatch.setattr(sector_data, name, _failed_provider)


def test_boards_to_agent_format_rejects_all_zero_but_preserves_rows() -> None:
    zero = _item()
    result = sector_data.boards_to_agent_format(
        {
            "concept": {"items": [zero], "provider": "eastmoney"},
            "industry": {"items": [zero], "provider": "eastmoney"},
        }
    )

    assert result["available"] is False
    assert result["concept"]["leaders"][0]["pct_change"] == 0.0
    assert result["concept"]["laggards"][0]["latest"] == 0.0
    assert result["industry"]["count"] == 1


@pytest.mark.parametrize("field", ["pct_change", "latest", "amount"])
def test_boards_to_agent_format_accepts_any_nonzero_market_field(field: str) -> None:
    values = {"pct_change": 0.0, "latest": 0.0, "amount": 0.0, field: 1.25}
    result = sector_data.boards_to_agent_format(
        {
            "concept": {"items": [_item(**values)], "provider": "eastmoney"},
            "industry": {"items": [], "provider": "eastmoney"},
        }
    )

    assert result["available"] is True


def test_zero_data_provider_falls_back_and_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = Mock()
    cache.get.return_value = (None, None, False)
    monkeypatch.setattr(sector_data, "_sector_cache", cache)
    eastmoney = Mock(return_value=[_item()])
    good = _item(pct_change=2.5, latest=10.0, amount=1000.0)
    sina = Mock(return_value=[good])
    monkeypatch.setattr(sector_data, "fetch_eastmoney_boards", eastmoney)
    monkeypatch.setattr(sector_data, "fetch_sina_boards", sina)
    monkeypatch.setattr(sector_data, "fetch_tdx_boards", _failed_provider)
    monkeypatch.setattr(sector_data, "fetch_ths_change_boards", _failed_provider)

    items, provider = sector_data._fetch_with_fallback("concept", 30)

    assert items == [good]
    assert provider == "sina"
    eastmoney.assert_called_once()
    sina.assert_called_once()
    cache.set.assert_called_once_with("concept", sector_data._items_to_dicts([good]), "sina")


def test_fresh_zero_cache_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = Mock()
    cache.get.return_value = ([asdict(_item())], "eastmoney", True)
    monkeypatch.setattr(sector_data, "_sector_cache", cache)
    good = _item(latest=8.5)
    eastmoney = Mock(return_value=[good])
    monkeypatch.setattr(sector_data, "fetch_eastmoney_boards", eastmoney)
    monkeypatch.setattr(sector_data, "fetch_sina_boards", _failed_provider)
    monkeypatch.setattr(sector_data, "fetch_tdx_boards", _failed_provider)
    monkeypatch.setattr(sector_data, "fetch_ths_change_boards", _failed_provider)

    items, provider = sector_data._fetch_with_fallback("concept", 30)

    assert items == [good]
    assert provider == "eastmoney"
    eastmoney.assert_called_once()


def test_fresh_nonzero_cache_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    cached = asdict(_item(amount="1200.5"))
    cache = Mock()
    cache.get.return_value = ([cached], "eastmoney", True)
    monkeypatch.setattr(sector_data, "_sector_cache", cache)
    _patch_failed_providers(monkeypatch)

    items, provider = sector_data._fetch_with_fallback("concept", 30)

    assert provider == "eastmoney_cache"
    assert len(items) == 1
    assert items[0].amount == 1200.5


def test_stale_all_zero_cache_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = Mock()
    cache.get.return_value = ([asdict(_item())], "eastmoney", False)
    monkeypatch.setattr(sector_data, "_sector_cache", cache)
    _patch_failed_providers(monkeypatch)

    with pytest.raises(sector_data.SectorDataUnavailableError):
        sector_data._fetch_with_fallback("concept", 30)

    cache.set.assert_not_called()


@pytest.mark.parametrize("collection", ["leaders", "laggards", "items"])
@pytest.mark.parametrize("field", ["pct_change", "latest", "amount"])
def test_boards_have_market_data_checks_agent_collections(collection: str, field: str) -> None:
    row = {"pct_change": 0, "latest": None, "amount": "invalid", field: "3.5"}
    boards = {
        "available": True,
        "concept": {"leaders": [], "laggards": [], collection: [row]},
        "industry": {"leaders": [asdict(_item())]},
    }

    assert sector_data.boards_have_market_data(boards) is True


def test_boards_have_market_data_ignores_zero_missing_and_invalid_values() -> None:
    boards = {
        "concept": {
            "leaders": [asdict(_item())],
            "laggards": [{"pct_change": None, "latest": "--", "amount": "invalid"}],
            "items": [{"pct_change": "nan", "latest": "inf", "amount": 0}],
        },
        "industry": {"items": [None, "not-a-record"]},
    }

    assert sector_data.boards_have_market_data(boards) is False
    assert sector_data.boards_have_market_data(None) is False


@pytest.mark.parametrize(
    "quotes",
    [
        None,
        [],
        [{}],
        [{"price": 0, "latest": 0, "pct_change": 0, "amount": 0}],
        [{"price": "nan"}],
        [{"latest": "inf"}],
    ],
)
def test_quotes_have_market_data_rejects_empty_zero_and_invalid(quotes) -> None:
    assert sector_data.quotes_have_market_data(quotes) is False


@pytest.mark.parametrize("field", ["price", "latest", "pct_change", "amount"])
def test_quotes_have_market_data_accepts_nonzero_numeric_fields(field: str) -> None:
    assert sector_data.quotes_have_market_data([{field: "3.5"}]) is True


@pytest.mark.parametrize(
    "sentiment",
    [
        None,
        [],
        {},
        {"errors": ["all providers failed"]},
        {"up_count": None, "down_count": "--"},
        {"limit_up_count": True},
        {"limit_up_count": "nan"},
        {"up_count": "inf", "down_count": "-inf"},
        {
            "up_count": 0,
            "down_count": 0,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "consecutive_height": 0,
            "first_board_count": 0,
            "broken_board_rate": 0,
        },
    ],
)
def test_sentiment_has_market_data_rejects_missing_zero_and_invalid(sentiment) -> None:
    assert sector_data.sentiment_has_market_data(sentiment) is False


@pytest.mark.parametrize(
    "field",
    [
        "up_count",
        "down_count",
        "limit_up_count",
        "limit_down_count",
        "consecutive_height",
        "first_board_count",
        "broken_board_rate",
    ],
)
def test_sentiment_has_market_data_accepts_positive_observed_metrics(field: str) -> None:
    assert sector_data.sentiment_has_market_data({field: "3.5"}) is True


def test_gator_ignores_unavailable_zero_board(monkeypatch: pytest.MonkeyPatch) -> None:
    from qing_investment.agent.graph import nodes

    monkeypatch.setattr(
        sector_data,
        "get_sector_strength_snapshot",
        lambda top_n: {
            "available": False,
            "industry": {
                "leaders": [
                    {
                        "code": "hangye_ZA01",
                        "name": "农业",
                        "pct_change": 0.0,
                        "latest": 0.0,
                        "amount": 0.0,
                    }
                ]
            },
        },
    )

    assert nodes._gator_sector_snapshot() == {
        "top_sector_name": None,
        "top_sector_pct": None,
        "top_sector_red_ratio": None,
    }


def _patch_gator_index_data(monkeypatch: pytest.MonkeyPatch, values):
    from qing_investment import marketdata
    from qing_investment.agent.graph import nodes
    from qing_investment.monitor.rules import gator_rules

    codes = ("sh000001", "sz399006", "sh000300", "sh000852")
    quotes = [{"code": code, "change_pct": value} for code, value in zip(codes, values)]
    monkeypatch.setattr(marketdata, "get_quotes", lambda requested: {"quotes": quotes})
    monkeypatch.setattr(nodes, "_gator_sector_snapshot", lambda: {})
    monkeypatch.setattr(nodes, "_gator_broker_limit_up", lambda: {})
    monkeypatch.setattr(nodes, "_gator_fund_snapshot", lambda: {})
    monkeypatch.setattr(nodes, "_gator_basis_snapshot", lambda market: {})
    unknown = Mock(level=Mock(value="unknown"), detail="")
    monkeypatch.setattr(nodes, "_gator_emotion_ice", lambda market: unknown)
    monkeypatch.setattr(
        nodes, "_gator_hedge_assessment", lambda: (unknown, Mock(value="unknown"))
    )
    monkeypatch.setattr(
        gator_rules,
        "assess_stop_falling",
        lambda **kwargs: Mock(met_count=0, total_count=0, stance="继续观望", signals=[]),
    )
    monkeypatch.setattr(gator_rules, "assess_scissors", lambda *args: unknown)
    return nodes


@pytest.mark.parametrize("change_pct", [0, "nan", "inf", "-inf"])
def test_gator_rejects_unusable_index_data(monkeypatch: pytest.MonkeyPatch, change_pct) -> None:
    nodes = _patch_gator_index_data(monkeypatch, (change_pct,) * 4)

    assert nodes._load_gator_rules_snapshot() == {
        "available": False,
        "reason": "指数数据不可用",
    }


def test_gator_normalizes_nonfinite_index_data(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = _patch_gator_index_data(monkeypatch, (1.2, "nan", 0, 0))

    snapshot = nodes._load_gator_rules_snapshot()

    assert snapshot["available"] is True
    assert snapshot["market_pct"] == {
        "sh_pct": 1.2,
        "cyb_pct": None,
        "hs300_pct": 0.0,
        "zz2000_pct": 0.0,
    }
