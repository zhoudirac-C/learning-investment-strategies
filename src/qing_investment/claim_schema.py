from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_INTENSITY = {"high", "medium", "low"}

VALID_CLAIM_TYPES = {
    "market-cycle",
    "sector-theme",
    "stock-view",
    "methodology",
    "risk",
    "technical-signal",
    "technical-knowledge",
    "macro",
    "operation",
    "catalyst",
    "general",
}

VALID_TIMEFRAMES = {"intraday", "short-term", "trend", "industry", "permanent"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_STATUS = {"active", "superseded", "contradicted", "expired", "case-only"}

# 话语性质（2026-09-17 新增，四值）：
#   fact          = 事实陈述/转述（行情数据、涨幅榜、政策转述、研报引用、公司资料）
#   view          = 该 up 对具体标的/板块/事件的判断（看好/看空、操作建议、选股判据、方法论）
#   market-regime = 对「市场/情绪/风格处于什么阶段」的定性定位
#                   （周期位置、级别判定、性质定性，如「反弹非反转」「情绪周期尾部释放」「混沌期」）
#   mixed         = 事实与判断兼有且不可拆分（拆分时优先只提判断部分，事实进 evidence_quote）
VALID_STANCE = {"fact", "view", "market-regime", "mixed"}

REQUIRED_FIELDS = {
    "id",
    "source_path",
    "source_date",
    "source_type",
    "up_id",
    "extracted_at",
    "claim_type",
    "subject",
    "timeframe",
    "statement",
    "evidence_quote",
    "interpretation",
    "confidence",
    "status",
    "intensity",
    "supersedes",
    "contradicts",
    "links",
}

# 非必填但受认可的字段（多 up 体系扩展）
OPTIONAL_FIELDS = {
    "up_name",          # up 显示名（非主键，可缺失）
    "disagrees_with",   # 不同 up 之间的观点分歧（与 supersedes/contradicts 区分）
    "related_stocks",
    "tags",
    "topic",
    "stance",           # 话语性质 fact/view/market-regime/mixed（2026-09-17 新增，非必填）
}

# 虚拟 up_id：非 up 来源的内容
VIRTUAL_UP_IDS = {
    "chanlun-original",  # 缠中说禅原著课程
}


@dataclass(frozen=True)
class Claim:
    id: str
    source_path: str
    source_date: str
    source_type: str
    up_id: str
    extracted_at: str
    claim_type: str
    subject: str
    timeframe: str
    statement: str
    evidence_quote: str
    interpretation: str
    confidence: str
    status: str
    intensity: str
    supersedes: list[str]
    contradicts: list[str]
    links: dict[str, list[str]]
    up_name: str = ""
    disagrees_with: list[str] = None  # type: ignore[assignment]
    stance: str = ""                  # 话语性质（四值，2026-09-17 新增，可空）

    def __post_init__(self) -> None:
        if self.disagrees_with is None:
            object.__setattr__(self, "disagrees_with", [])


def validate_claim_dict(data: dict[str, Any]) -> Claim:
    missing = sorted(REQUIRED_FIELDS - set(data))
    if missing:
        raise ValueError(f"Missing required claim fields: {', '.join(missing)}")

    _require_enum("claim_type", data["claim_type"], VALID_CLAIM_TYPES)
    _require_enum("timeframe", data["timeframe"], VALID_TIMEFRAMES)
    _require_enum("confidence", data["confidence"], VALID_CONFIDENCE)
    _require_enum("intensity", data["intensity"], VALID_INTENSITY)
    _require_enum("status", data["status"], VALID_STATUS)

    if not isinstance(data["supersedes"], list):
        raise ValueError("supersedes must be a list")
    if not isinstance(data["contradicts"], list):
        raise ValueError("contradicts must be a list")
    if not isinstance(data["links"], dict):
        raise ValueError("links must be a dict")

    # up_id 必填且非空（虚拟 up 用 VIRTUAL_UP_IDS）
    up_id_val = str(data["up_id"]).strip()
    if not up_id_val:
        raise ValueError("up_id must be a non-empty string")

    # disagrees_with 若存在必须是 list
    dw = data.get("disagrees_with")
    if dw is not None and not isinstance(dw, list):
        raise ValueError("disagrees_with must be a list")

    # stance 非必填；若存在必须是合法枚举（2026-09-17 新增）
    stance_val = data.get("stance")
    if stance_val not in (None, ""):
        _require_enum("stance", str(stance_val), VALID_STANCE)

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
        up_id=up_id_val,
        extracted_at=str(data["extracted_at"]),
        claim_type=str(data["claim_type"]),
        subject=str(data["subject"]),
        timeframe=str(data["timeframe"]),
        statement=str(data["statement"]),
        evidence_quote=str(data["evidence_quote"]),
        interpretation=str(data["interpretation"]),
        confidence=str(data["confidence"]),
        status=str(data["status"]),
        intensity=str(data["intensity"]),
        supersedes=[str(item) for item in data["supersedes"]],
        contradicts=[str(item) for item in data["contradicts"]],
        links=links,
        up_name=str(data.get("up_name") or ""),
        disagrees_with=[str(i) for i in (dw or [])],
        stance=str(data.get("stance") or ""),
    )


def _require_enum(field: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise ValueError(f"Invalid {field}: {value}. Allowed: {', '.join(sorted(allowed))}")
