from qing_investment.mention_extractor import extract_mentions


def test_extract_mentions_finds_stock_codes_and_known_terms():
    text = "中际旭创 300308 和 中国长城 000066 属于国产算力与 CPO 方向。"
    mentions = extract_mentions(text)
    assert "300308" in mentions.stock_codes
    assert "000066" in mentions.stock_codes
    assert "中际旭创" in mentions.stock_names
    assert "中国长城" in mentions.stock_names
    assert "国产算力" in mentions.sectors
    assert "CPO" in mentions.sectors
