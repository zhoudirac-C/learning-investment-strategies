import pytest

from qing_investment.claim_schema import Claim, validate_claim_dict


def valid_claim_dict():
    return {
        "id": "claim-20260516-001",
        "source_path": "sources/raw/财经/2026-05-16-早盘-样例.md",
        "source_date": "2026-05-16",
        "source_type": "早盘",
        "extracted_at": "2026-05-16T09:00:00+08:00",
        "claim_type": "market-cycle",
        "subject": "国产算力",
        "timeframe": "trend",
        "statement": "国产算力仍是当前主线之一。",
        "evidence_quote": "国产算力这条线还没有结束。",
        "interpretation": "该表述应进入板块主线跟踪，但是否升级为长期方法论需要后续 review。",
        "confidence": "high",
        "status": "active",
        "supersedes": [],
        "contradicts": [],
        "links": {"wiki_pages": [], "methodology_pages": [], "cases": []},
    }


def test_validate_claim_accepts_complete_claim():
    claim = validate_claim_dict(valid_claim_dict())
    assert isinstance(claim, Claim)
    assert claim.id == "claim-20260516-001"
    assert claim.claim_type == "market-cycle"


def test_validate_claim_rejects_missing_required_field():
    data = valid_claim_dict()
    data.pop("evidence_quote")
    with pytest.raises(ValueError, match="evidence_quote"):
        validate_claim_dict(data)


def test_validate_claim_rejects_unknown_enum():
    data = valid_claim_dict()
    data["status"] = "fresh"
    with pytest.raises(ValueError, match="status"):
        validate_claim_dict(data)
