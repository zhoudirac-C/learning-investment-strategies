"""Tests for discover_claim_relations 时序守卫（2026-10-24）。

背景：supersedes 语义是「新取代旧」。旧批次补扫（--all-missing /
--neo4j-zero-edges 重扫历史 claim）时，LLM 偶发把「源该被目标取代」
误标为源 supersedes 目标，写入即构成「历史观点替代最近观点」。
process_claim 现内置时序守卫：源 source_date 早于目标时丢弃反向
supersedes（降级为 none 并记录拦截原因）；缺日期放行，由反向边审计兜底。

回归守护：本文件
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qing_investment.agent.tools.discover_claim_relations import (
    _parse_source_date,
    process_claim,
)


class _FakeEmb:
    def encode(self, text):
        class _V:
            def tolist(self):
                return [0.1] * 512
        return _V()


class _FakeQdrant:
    """只返回一个固定候选（score 0.9）。"""

    def __init__(self, cand_id: str):
        self._cand = {
            "payload": {
                "claim_id": cand_id,
                "subject": "候选主题",
                "statement": "候选表述",
                "source_date": "2026-10-01",
                "claim_type": "market-view",
                "up_id": "up-q",
                "up_name": "青枫浦上Q",
            },
            "score": 0.9,
        }

    def search(self, vec, collection, limit):
        return [self._cand]


class _FakeNeo4j:
    """get_claim_evolution 返回扁平 dict（真实接口 2026-06-08 后的格式）。"""

    def __init__(self, source_date: str):
        self._d = source_date

    def get_claim_evolution(self, claim_id):
        return [{
            "id": claim_id,
            "subject": "候选主题",
            "statement": "候选表述",
            "interpretation": "",
            "source_date": self._d,
            "claim_type": "market-view",
        }]


class _FakeLLM:
    """固定回复指定关系。"""

    def __init__(self, relation: str):
        self._relation = relation

    def invoke(self, prompt):
        class _R:
            def __init__(self, content):
                self.content = content
        import json
        return _R(json.dumps({"relation": self._relation, "reason": "测试"}))


def _src_claim(source_date: str) -> dict:
    return {
        "id": "claim-src",
        "subject": "源主题",
        "statement": "源表述",
        "interpretation": "",
        "source_date": source_date,
        "claim_type": "market-view",
        "up_id": "up-q",
        "up_name": "青枫浦上Q",
    }


def _run(src_date: str, tgt_date: str, relation: str = "supersedes") -> dict:
    return process_claim(
        _src_claim(src_date),
        _FakeQdrant("claim-target"),
        _FakeNeo4j(tgt_date),
        _FakeEmb(),
        _FakeLLM(relation),
        dry_run=True,
    )


def test_guard_blocks_old_source_superseding_new_target():
    """源(10-01) 早于目标(10-17) + LLM 误判 supersedes → 必须拦截。"""
    r = _run("2026-10-01", "2026-10-17")
    assert r["supersedes"] == []
    pair = r["pairs"][0]
    assert pair["relation"] == "none"
    assert "时序守卫拦截" in pair["reason"]


def test_guard_allows_new_source_superseding_old_target():
    """源(10-17) 新于目标(10-01) → 正常写入 supersedes。"""
    r = _run("2026-10-17", "2026-10-01")
    assert r["supersedes"] == ["claim-target"]


def test_guard_allows_same_date():
    """同日 → 允许（无先后可分）。"""
    r = _run("2026-10-17", "2026-10-17")
    assert r["supersedes"] == ["claim-target"]


def test_guard_passes_when_dates_missing():
    """缺日期 → 放行（交由反向边审计兜底），不得静默吞掉。"""
    r = _run("", "2026-10-01")
    assert r["supersedes"] == ["claim-target"]


def test_guard_does_not_touch_contradicts():
    """守卫只管 supersedes 方向；contradicts 对称，不受影响。"""
    r = _run("2026-10-01", "2026-10-17", relation="contradicts")
    assert r["contradicts"] == ["claim-target"]


def test_parse_source_date_formats():
    assert _parse_source_date("2026-10-17") == "2026-10-17"
    assert _parse_source_date("2026/10/17") == "2026-10-17"
    assert _parse_source_date("2026.10.17") == "2026-10-17"
    assert _parse_source_date("20261017") == "2026-10-17"
    assert _parse_source_date(None) is None
    assert _parse_source_date("未知") is None
