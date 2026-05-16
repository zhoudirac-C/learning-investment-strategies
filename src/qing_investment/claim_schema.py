from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_CLAIM_TYPES = {
    "market-cycle",
    "sector-theme",
    "stock-view",
    "methodology",
    "risk",
    "technical-signal",
    "macro",
    "operation",
}

VALID_TIMEFRAMES = {"intraday", "short-term", "trend", "industry", "permanent"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_STATUS = {"active", "superseded", "contradicted", "expired", "case-only"}

REQUIRED_FIELDS = {
    "id",
    "source_path",
    "source_date",
    "source_type",
    "extracted_at",
    "claim_type",
    "subject",
    "timeframe",
    "statement",
    "evidence_quote",
    "interpretation",
    "confidence",
    "status",
    "supersedes",
    "contradicts",
    "links",
}


@dataclass(frozen=True)
class Claim:
    id: str
    source_path: str
    source_date: str
    source_type: str
    extracted_at: str
    claim_type: str
    subject: str
    timeframe: str
    statement: str
    evidence_quote: str
    interpretation: str
    confidence: str
    status: str
    supersedes: list[str]
    contradicts: list[str]
    links: dict[str, list[str]]


def validate_claim_dict(data: dict[str, Any]) -> Claim:
    missing = sorted(REQUIRED_FIELDS - set(data))
    if missing:
        raise ValueError(f"Missing required claim fields: {', '.join(missing)}")

    _require_enum("claim_type", data["claim_type"], VALID_CLAIM_TYPES)
    _require_enum("timeframe", data["timeframe"], VALID_TIMEFRAMES)
    _require_enum("confidence", data["confidence"], VALID_CONFIDENCE)
    _require_enum("status", data["status"], VALID_STATUS)

    if not isinstance(data["supersedes"], list):
        raise ValueError("supersedes must be a list")
    if not isinstance(data["contradicts"], list):
        raise ValueError("contradicts must be a list")
    if not isinstance(data["links"], dict):
        raise ValueError("links must be a dict")

    links = {
        "wiki_pages": list(data["links"].get("wiki_pages", [])),
        "methodology_pages": list(data["links"].get("methodology_pages", [])),
        "cases": list(data["links"].get("cases", [])),
    }

    return Claim(
        id=str(data["id"]),
        source_path=str(data["source_path"]),
        source_date=str(data["source_date"]),
        source_type=str(data["source_type"]),
        extracted_at=str(data["extracted_at"]),
        claim_type=str(data["claim_type"]),
        subject=str(data["subject"]),
        timeframe=str(data["timeframe"]),
        statement=str(data["statement"]),
        evidence_quote=str(data["evidence_quote"]),
        interpretation=str(data["interpretation"]),
        confidence=str(data["confidence"]),
        status=str(data["status"]),
        supersedes=[str(item) for item in data["supersedes"]],
        contradicts=[str(item) for item in data["contradicts"]],
        links=links,
    )


def _require_enum(field: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise ValueError(f"Invalid {field}: {value}. Allowed: {', '.join(sorted(allowed))}")
