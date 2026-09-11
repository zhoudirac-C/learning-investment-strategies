"""symbol.py 单测：号段判定 + 归一化 + 矛盾拒绝。"""

import pytest

from qing_investment.marketdata.symbol import (
    is_index_code,
    norm_ticker,
    prefix_for,
    resolve_symbol,
)


class TestNormTicker:
    def test_plain(self):
        assert norm_ticker("600519") == "600519"

    def test_prefix(self):
        assert norm_ticker("SH600519") == "600519"
        assert norm_ticker("sh600519") == "600519"
        assert norm_ticker("sz000016") == "000016"

    def test_suffix(self):
        assert norm_ticker("600519.SH") == "600519"
        assert norm_ticker("000001.SZ") == "000001"

    def test_index_prefixed(self):
        assert norm_ticker("sh000932") == "000932"
        assert norm_ticker("883418") == "883418"

    def test_reject_garbage(self):
        with pytest.raises(ValueError):
            norm_ticker("6005190")  # 7位
        with pytest.raises(ValueError):
            norm_ticker("贵州茅台")
        with pytest.raises(ValueError):
            norm_ticker("")

    def test_reject_contradiction(self):
        with pytest.raises(ValueError):
            norm_ticker("SH000001.SZ")
        with pytest.raises(ValueError):
            norm_ticker("sz600519")  # 6 开头沪市票标了 sz


class TestPrefixFor:
    def test_segment_rules(self):
        assert prefix_for("600519") == "sh"      # 6 沪股
        assert prefix_for("510300") == "sh"      # 5 沪ETF（不能判 sz！）
        assert prefix_for("588000") == "sh"      # 科创ETF
        assert prefix_for("900901") == "sh"      # 沪B
        assert prefix_for("159915") == "sz"
        assert prefix_for("300750") == "sz"
        assert prefix_for("920982") == "bj"      # 92 先于 9x 判断
        assert prefix_for("900901") == "sh"

    def test_sh_index_whitelist(self):
        assert prefix_for("000300") == "sh"
        assert prefix_for("000985") == "sh"
        assert prefix_for("000688") == "sh"

    def test_kind_disambiguation(self):
        # 000001 双义：上证指数 vs 平安银行
        assert prefix_for("000001", kind="index") == "sh"
        assert prefix_for("000001", kind="stock") == "sz"

    def test_index_kind(self):
        assert prefix_for("399001", kind="index") == "sz"
        assert prefix_for("880823", kind="index") == "sh"  # TDX 独有指数

    def test_explicit_prefix_passthrough(self):
        assert prefix_for("sh000001") == "sh"
        assert prefix_for("sz399006") == "sz"

    def test_contradiction_rejected(self):
        with pytest.raises(ValueError):
            prefix_for("sz600519")


class TestResolveSymbol:
    def test_pairs(self):
        assert resolve_symbol("600519") == ("sh", "600519")
        assert resolve_symbol("sh000932") == ("sh", "000932")
        assert resolve_symbol("512400") == ("sh", "512400")

    def test_is_index_code(self):
        assert is_index_code("sh000001")
        assert not is_index_code("600519")
