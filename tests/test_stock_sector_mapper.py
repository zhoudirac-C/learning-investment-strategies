from qing_investment.agent.tools import stock_sector_mapper as mapper


def _realtime_position() -> mapper.StockSectorPosition:
    return mapper.StockSectorPosition(
        sector_node="bank",
        sector_name="银行",
        board_type="industry",
        rank=2,
        total=40,
        changepercent=4.2,
        mktcap=600_0000,
        turnoverratio=2.0,
        position_tag="前排强势",
        position_reason="实时排名第2/40",
    )


def test_realtime_ranking_wins_over_qing_historical_position(monkeypatch):
    monkeypatch.setattr(
        mapper, "get_stock_sectors", lambda code: [{"node": "bank"}]
    )
    monkeypatch.setattr(
        mapper,
        "get_stock_rank_in_sector",
        lambda code, sector_node: _realtime_position(),
    )

    result = mapper.get_stock_positioning(
        "600000",
        up_position="历史龙头",
        up_position_source="2026-01-02 claim-history",
    )

    assert result.final_position == "前排强势"
    assert "实时" in result.final_reason
    assert "历史参考" in result.final_reason
    assert "2026-01-02" in result.final_reason


def test_missing_realtime_ranking_degrades_to_unknown(monkeypatch):
    monkeypatch.setattr(mapper, "get_stock_sectors", lambda code: [])

    result = mapper.get_stock_positioning(
        "600000",
        up_position="历史龙头",
        up_position_source="2026-01-02 claim-history",
    )

    assert result.final_position == "未知"
    assert "实时板块排名不可用" in result.final_reason
    assert "历史参考" in result.final_reason
    assert "2026-01-02" in result.final_reason
    assert "唯一参考" not in result.final_reason
