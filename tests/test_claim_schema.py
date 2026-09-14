import pytest

from qing_investment.claim_schema import Claim, validate_claim_dict


def valid_claim_dict():
    return {
        "id": "claim-20260516-001",
        "source_path": "sources/raw/财经/2026-05-16-早盘-样例.md",
        "source_date": "2026-05-16",
        "source_type": "早盘",
        "up_id": "1420210197",
        "extracted_at": "2026-05-16T09:00:00+08:00",
        "claim_type": "market-cycle",
        "subject": "国产算力",
        "timeframe": "trend",
        "statement": "国产算力仍是当前主线之一。",
        "evidence_quote": "国产算力这条线还没有结束。",
        "interpretation": "该表述应进入板块主线跟踪，但是否升级为长期方法论需要后续 review。",
        "confidence": "high",
        "status": "active",
        "intensity": "high",
        "supersedes": [],
        "contradicts": [],
        "links": {"wiki_pages": [], "methodology_pages": [], "cases": []},
    }


def test_validate_claim_accepts_complete_claim():
    claim = validate_claim_dict(valid_claim_dict())
    assert isinstance(claim, Claim)
    assert claim.id == "claim-20260516-001"
    assert claim.claim_type == "market-cycle"
    assert claim.intensity == "high"


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


def test_validate_claim_rejects_invalid_intensity():
    data = valid_claim_dict()
    data["intensity"] = "extreme"
    with pytest.raises(ValueError, match="intensity"):
        validate_claim_dict(data)


def test_validate_claim_rejects_missing_intensity():
    data = valid_claim_dict()
    data.pop("intensity")
    with pytest.raises(ValueError, match="intensity"):
        validate_claim_dict(data)


def test_validate_claim_accepts_all_intensity_levels():
    for level in ("high", "medium", "low"):
        data = valid_claim_dict()
        data["intensity"] = level
        claim = validate_claim_dict(data)
        assert claim.intensity == level


# ── 多 up 体系扩展（2026-09-14）─────────────────────────

def test_validate_claim_exposes_up_id():
    claim = validate_claim_dict(valid_claim_dict())
    assert claim.up_id == "1420210197"


def test_validate_claim_rejects_missing_up_id():
    data = valid_claim_dict()
    data.pop("up_id")
    with pytest.raises(ValueError, match="up_id"):
        validate_claim_dict(data)


def test_validate_claim_rejects_empty_up_id():
    data = valid_claim_dict()
    data["up_id"] = "   "
    with pytest.raises(ValueError, match="up_id"):
        validate_claim_dict(data)


def test_validate_claim_accepts_virtual_up_id_for_chanlun():
    """缠论原著课程用虚拟 up_id 标识，非 up 来源。"""
    data = valid_claim_dict()
    data["up_id"] = "chanlun-original"
    data["up_name"] = "缠中说禅"
    claim = validate_claim_dict(data)
    assert claim.up_id == "chanlun-original"
    assert claim.up_name == "缠中说禅"


def test_validate_claim_up_name_defaults_empty():
    """up_name 为可选字段，缺失时默认为空串。"""
    claim = validate_claim_dict(valid_claim_dict())
    assert claim.up_name == ""


def test_validate_claim_accepts_disagrees_with_list():
    """disagrees_with 表达不同 up 的观点分歧。"""
    data = valid_claim_dict()
    data["disagrees_with"] = ["claim-20260901-005-c"]
    claim = validate_claim_dict(data)
    assert claim.disagrees_with == ["claim-20260901-005-c"]


def test_validate_claim_disagrees_with_defaults_empty():
    claim = validate_claim_dict(valid_claim_dict())
    assert claim.disagrees_with == []


def test_validate_claim_rejects_non_list_disagrees_with():
    data = valid_claim_dict()
    data["disagrees_with"] = "claim-20260901-005-c"
    with pytest.raises(ValueError, match="disagrees_with"):
        validate_claim_dict(data)
