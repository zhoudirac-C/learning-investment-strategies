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


class TestFindAlternativesFromKb:
    """M0-Chain 知识库 fallback（direction_pool 无配置时）。"""

    def _kb(self, tmp_path):
        from investment_engine.industry_chain.store import save_chain

        save_chain({
            "chain_id": "kb-chain", "name": "测试链", "thesis": "t",
            "last_verified": "2026-08-31", "current_stage": "阶段1-启动期",
            "segments": [{"id": "seg-up", "name": "上游材料"},
                         {"id": "seg-mid", "name": "中游制造"}],
            "mappings": [
                {"code": "000636", "name": "风华高科", "segment": "seg-mid",
                 "relation": "龙头", "elasticity": "core"},
                {"code": "300285", "name": "国瓷材料", "segment": "seg-up",
                 "relation": "材料", "elasticity": "elastic"},
            ],
        }, base_dir=tmp_path)
        save_chain({
            "chain_id": "kb-watch", "name": "观察链", "thesis": "t",
            "last_verified": "2026-08-31",  # 无 current_stage → 阶段0
            "segments": [{"id": "seg-a", "name": "上游"}],
            "mappings": [
                {"code": "000777", "name": "观察股A", "segment": "seg-a",
                 "relation": "龙头", "elasticity": "core"},
                {"code": "000888", "name": "观察股B", "segment": "seg-a",
                 "relation": "跟风", "elasticity": "concept"},
            ],
        }, base_dir=tmp_path)
        return tmp_path

    def test_kb_fallback_recommends_other_segments(self, tmp_path):
        base = self._kb(tmp_path)
        scanner = ChainAwareScanner()
        alts = scanner.find_alternatives_from_kb("000636.SZ", base_dir=base)
        assert len(alts) == 1
        assert alts[0].code == "300285.SZ"
        assert alts[0].segment == "上游材料"
        assert "测试链" in alts[0].reason and "阶段1-启动期" in alts[0].reason

    def test_kb_fallback_skips_stage0_chains(self, tmp_path):
        base = self._kb(tmp_path)
        scanner = ChainAwareScanner()
        # 000777 只在阶段0观察链里 → 不推荐
        assert scanner.find_alternatives_from_kb("000777.SZ", base_dir=base) == []

    def test_kb_fallback_unknown_stock(self, tmp_path):
        base = self._kb(tmp_path)
        scanner = ChainAwareScanner()
        assert scanner.find_alternatives_from_kb("999999.SZ", base_dir=base) == []
