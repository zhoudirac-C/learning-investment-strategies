from qing_investment.agent.graph.nodes import shard_router


def test_shard_router_fan_out():
    state = {
        "watchlist": [
            {"code": "000001.SZ", "name": "A", "theme": "t1"},
            {"code": "000002.SZ", "name": "B", "theme": "t1"},
            {"code": "000003.SZ", "name": "C", "theme": "t2"},
        ],
        "positions": [],
        "shard_size": 2,
        "core_only": False,
    }
    sends = shard_router(state)
    assert len(sends) >= 2
    for s in sends:
        assert s.node == "stock_scanner_shard"
        assert "watchlist_shard" in s.arg


def test_shard_size_zero_disables_sharding():
    state = {
        "watchlist": [
            {"code": "000001.SZ", "name": "A", "theme": "t1"},
            {"code": "000002.SZ", "name": "B", "theme": "t1"},
            {"code": "000003.SZ", "name": "C", "theme": "t2"},
        ],
        "positions": [],
        "shard_size": 0,
        "core_only": False,
    }
    sends = shard_router(state)
    assert len(sends) == 1
    assert sends[0].node == "stock_scanner_shard"
    shard = sends[0].arg["watchlist_shard"]
    assert shard["name"] == "全部标的"
    assert len(shard["items"]) == 3
