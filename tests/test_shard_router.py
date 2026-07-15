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
