import pytest

from qing_investment.agent.tools.watchlist_sharder import (
    WatchlistShard,
    shard_watchlist,
    shard_to_context,
)


def test_priority_shard_contains_p1_and_positions():
    watchlist = {
        "themes": [
            {
                "name": "mlcc",
                "stocks": [
                    {"code": "002409", "name": "雅克科技", "priority": "P1-核心", "theme": "mlcc"},
                    {"code": "000636", "name": "风华高科", "priority": "P2-重点", "theme": "mlcc"},
                    {"code": "603678", "name": "火炬电子", "priority": "P2-重点", "theme": "mlcc"},
                ],
            },
            {
                "name": "光通信",
                "stocks": [
                    {"code": "601869", "name": "长飞光纤", "priority": "P3-跟踪", "theme": "光通信"},
                ],
            },
        ]
    }
    positions = {"accounts": [{"positions": [{"code": "002409", "name": "雅克科技"}]}]}

    shards = shard_watchlist(watchlist, positions, max_items=2)

    assert shards[0].name == "priority"
    assert shards[0].is_priority is True
    assert len(shards[0].items) == 1
    assert shards[0].items[0]["code"] == "002409"

    theme_shards = shards[1:]
    assert any(s.name.startswith("mlcc") and len(s.items) <= 2 for s in theme_shards)
    assert sum(len(s.items) for s in theme_shards) == 3


def test_list_input_and_deduplication():
    watchlist = [
        {"code": "000001", "name": "平安银行", "priority": "P2", "theme": "银行"},
        {"code": "000001", "name": "平安银行", "priority": "P2", "theme": "银行"},
        {"code": "000002", "name": "万科A", "priority": "P3", "theme": "地产"},
    ]
    shards = shard_watchlist(watchlist, positions=[], max_items=5)
    assert len(shards) == 2
    codes = [s.items[0]["code"] for s in shards]
    assert "000001" in codes
    assert "000002" in codes


def test_positions_as_list_supported():
    watchlist = [
        {"code": "600519", "name": "贵州茅台", "priority": "P2", "theme": "白酒"},
        {"code": "000858", "name": "五粮液", "priority": "P3", "theme": "白酒"},
    ]
    positions = [{"code": "600519", "name": "贵州茅台"}]
    shards = shard_watchlist(watchlist, positions, max_items=5)
    assert shards[0].name == "priority"
    assert shards[0].items[0]["code"] == "600519"


def test_shard_to_context_shape():
    shard = WatchlistShard(
        name="test",
        items=[{"code": "002409", "name": "雅克科技", "priority": "P1", "theme": "mlcc", "extra": "x"}],
        is_priority=True,
    )
    ctx = shard_to_context(shard)
    assert ctx["name"] == "test"
    assert ctx["is_priority"] is True
    assert ctx["items"] == [{"code": "002409", "name": "雅克科技", "priority": "P1", "theme": "mlcc"}]
