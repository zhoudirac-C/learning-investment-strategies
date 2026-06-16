from __future__ import annotations

from qing_investment.monitor.chain_scanner import ChainAwareScanner, ChainAlternative


def _sample_direction() -> dict:
    return {
        "id": "mlcc_super_cycle",
        "industry_chain": {
            "upstream": [
                {
                    "segment": "陶瓷粉体",
                    "stocks": [{"code": "300285.SZ", "name": "国瓷材料"}],
                    "pumped": False,
                }
            ],
            "midstream": [
                {
                    "segment": "MLCC制造",
                    "stocks": [
                        {"code": "000636.SZ", "name": "风华高科"},
                        {"code": "300408.SZ", "name": "三环集团"},
                    ],
                    "pumped": True,
                }
            ],
        },
    }


def test_find_alternatives_recommends_upstream():
    scanner = ChainAwareScanner()
    alts = scanner.find_alternatives("000636.SZ", _sample_direction())
    assert len(alts) == 1
    assert alts[0].code == "300285.SZ"
    assert alts[0].chain_position == "upstream"


def test_find_alternatives_returns_empty_for_unknown_stock():
    scanner = ChainAwareScanner()
    alts = scanner.find_alternatives("999999.SZ", _sample_direction())
    assert alts == []
