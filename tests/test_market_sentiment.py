from unittest.mock import MagicMock, patch

from qing_investment.agent.tools.market_sentiment import fetch_market_sentiment


def test_fetch_market_sentiment_structure():
    """验证情绪数据结构，所有 akshare 调用 mock 返回空/固定值。"""
    empty_df = MagicMock()
    empty_df.columns = ["涨跌幅"]
    empty_df.__len__ = lambda self: 0
    empty_df.__getitem__ = lambda self, key: MagicMock()

    with patch("akshare.stock_zh_a_spot_em") as mock_spot, \
         patch("akshare.stock_zt_pool_em") as mock_zt, \
         patch("akshare.stock_zt_pool_dtgc_em") as mock_dt:
        mock_spot.return_value = empty_df
        mock_zt.return_value = empty_df
        mock_dt.return_value = empty_df

        result = fetch_market_sentiment()

    assert "up_count" in result
    assert "down_count" in result
    assert "limit_up_count" in result
    assert "limit_down_count" in result
    assert "consecutive_height" in result
    assert "first_board_count" in result
    assert "broken_board_rate" in result
