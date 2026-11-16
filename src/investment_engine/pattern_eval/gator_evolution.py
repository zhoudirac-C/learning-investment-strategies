from __future__ import annotations

import copy
import difflib
import io
import json
import logging
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

import yaml
from ruamel.yaml import YAML

GATOR_UP_ID = "gator-ecyu-0001"
TERMINAL_REVIEW_STATES = {"applied", "reviewed-irrelevant", "rejected"}
STATUS_ACTIONS = {
    "irrelevant": "reviewed-irrelevant",
    "rejected": "rejected",
    "observing": "observing",
}
RULE_ACTIONS = {
    "reinforce",
    "refine",
    "contradict",
    "new_theme",
    "repair_provenance",
}
REFINE_FIELDS = {
    "description",
    "trigger",
    "steps",
    "thresholds",
    "table_rules",
    "falsification",
}
CANDIDATE_FIELDS = {
    "slug",
    "name",
    "description",
    "trigger",
    "steps",
    "thresholds",
    "table_rules",
    "falsification",
    "computable",
    "core",
    "validation",
}

logger = logging.getLogger(__name__)


def load_gator_claims(claims_dir: Path) -> list[dict]:
    claims_dir = Path(claims_dir)
    result = []
    seen_ids = set()
    for path in sorted(claims_dir.glob("claim-*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("跳过无法解析的 claim 文件 %s: %s", path.name, exc)
            continue
        if isinstance(data, dict) and isinstance(data.get("claims"), list):
            claims = data["claims"]
        elif isinstance(data, list):
            claims = data
        elif isinstance(data, dict) and data.get("id"):
            claims = [data]
        else:
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            if claim.get("school") != "gator" and claim.get("up_id") != GATOR_UP_ID:
                continue
            claim_id = claim.get("id")
            if claim_id:
                if claim_id in seen_ids:
                    raise ValueError(f"重复 claim_id: {claim_id}")
                seen_ids.add(claim_id)
            item = dict(claim)
            item["_claim_file"] = path.name
            result.append(item)
    return result


def _claim_map(claims_dir: Path) -> dict[str, dict]:
    result = {}
    for claim in load_gator_claims(claims_dir):
        claim_id = claim.get("id")
        if not claim_id:
            continue
        result[claim_id] = claim
    return result


def list_pending(*, patterns_path: Path, state_path: Path, claims_dir: Path) -> dict:
    doc = yaml.safe_load(Path(patterns_path).read_text(encoding="utf-8"))
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    claims = _claim_map(claims_dir)
    review = state.get("review_status", {}) or {}
    classifications = state.get("classifications", {}) or {}

    pending_review = []
    for claim_id, classification in sorted(classifications.items()):
        if claim_id not in claims:
            continue
        review_entry = review.get(claim_id) or {}
        status = review_entry.get("status", "pending-review")
        if status in TERMINAL_REVIEW_STATES:
            continue
        claim = claims[claim_id]
        pending_review.append(
            {
                "claim_id": claim_id,
                "source_date": str(claim.get("source_date", "")),
                "topic": claim.get("topic", ""),
                "review_status": status,
                **classification,
            }
        )

    unclassified = set(claims) - set(classifications)
    state_ids = (
        set(state.get("processed_claim_ids", []) or [])
        | set(classifications)
        | set(review)
    )
    orphans = state_ids - set(claims)
    unresolved = []
    for pattern in doc.get("patterns", []) or []:
        for drift in pattern.get("drift_flag", []) or []:
            if drift.get("resolution") == "pending":
                unresolved.append({"pattern_id": pattern.get("pattern_id"), **drift})

    return {
        "pending_review": pending_review,
        "unclassified_claim_ids": sorted(unclassified),
        "orphan_claim_ids": sorted(orphans),
        "unresolved_drifts": unresolved,
        "counts": {
            "pending_review": len(pending_review),
            "unclassified": len(unclassified),
            "orphans": len(orphans),
            "unresolved_drifts": len(unresolved),
        },
    }


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _norm(value: object) -> str:
    return " ".join(str(value or "").split())


def _load_patterns(patterns_path: Path):
    rt = YAML()
    rt.width = 4096
    return rt, rt.load(Path(patterns_path).read_text(encoding="utf-8"))


def _dump_rt(rt: YAML, doc: dict) -> str:
    buffer = io.StringIO()
    rt.dump(doc, buffer)
    return buffer.getvalue()


def _atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            tmp.write(text)
            tmp_name = tmp.name
        Path(tmp_name).replace(path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()


def _decision_claim_ids(decision: dict) -> list[str]:
    if decision.get("claim_ids") is not None:
        claim_ids = decision["claim_ids"]
        if not isinstance(claim_ids, list) or not all(
            isinstance(claim_id, str) and claim_id for claim_id in claim_ids
        ):
            raise ValueError("claim_ids 必须是非空字符串列表")
        return list(claim_ids)
    claim_id = decision.get("claim_id")
    return [claim_id] if isinstance(claim_id, str) and claim_id else []


def _decision_key(decision: dict) -> str:
    candidate = decision.get("candidate_pattern", {}) or {}
    identity = {
        "action": decision.get("action"),
        "claim_ids": sorted(_decision_claim_ids(decision)),
        "pattern_id": decision.get("pattern_id"),
        "slug": candidate.get("slug"),
    }
    return json.dumps(identity, ensure_ascii=False, sort_keys=True)


def _logged_keys(doc: dict) -> set[str]:
    return {
        change["decision_key"]
        for entry in doc.get("evolution_log", []) or []
        for change in entry.get("changes", []) or []
        if change.get("decision_key")
    }


def _claims_for(
    decision: dict, claims: dict[str, dict], repo_root: Path
) -> list[dict]:
    claim_ids = _decision_claim_ids(decision)
    if not claim_ids:
        raise ValueError("decision 缺 claim_id/claim_ids")
    result = []
    for claim_id in claim_ids:
        if claim_id not in claims:
            raise ValueError(f"未知 claim_id: {claim_id}")
        claim = claims[claim_id]
        source = claim.get("source_path")
        if not source or not (repo_root / source).exists():
            raise ValueError(f"{claim_id}: 原文路径不存在: {source}")
        if not _norm(claim.get("evidence_quote")):
            raise ValueError(f"{claim_id}: 缺 evidence_quote")
        result.append(claim)
    return result


def _source_date(claim: dict) -> str:
    value = str(claim.get("source_date") or "")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{claim.get('id')}: 无效 source_date: {value}") from exc
    return value


def validate_gator_document(
    doc: dict,
    repo_root: Path,
    *,
    allow_broken: set[str] | None = None,
    claims: dict[str, dict] | None = None,
) -> None:
    allow_broken = allow_broken or set()
    patterns = doc.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        raise ValueError("patterns 必须是非空列表")
    ids = [pattern.get("pattern_id") for pattern in patterns]
    if any(not pattern_id for pattern_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("pattern_id 缺失或重复")
    for pattern in patterns:
        pattern_id = pattern["pattern_id"]
        for field in (
            "school",
            "name",
            "chapter",
            "description",
            "trigger",
            "steps",
            "validation",
        ):
            if field not in pattern:
                raise ValueError(f"{pattern_id}: 缺字段 {field}")
        if pattern["school"] != "gator":
            raise ValueError(f"{pattern_id}: school 必须为 gator")
        source = pattern.get("source_path")
        if (
            source
            and pattern_id not in allow_broken
            and not (repo_root / source).exists()
        ):
            raise ValueError(f"{pattern_id}: source_path 不存在: {source}")
        source_claims = pattern.get("source_claims", []) or []
        if not isinstance(source_claims, list):
            raise ValueError(f"{pattern_id}: source_claims 必须是列表")
        if (
            str(pattern.get("provenance", "")).startswith("local-gator-evolution")
            and not source_claims
        ):
            raise ValueError(f"{pattern_id}: 本地演进 pattern 缺 source_claims")
        if source_claims and pattern.get("local_evidence_count") != len(
            set(source_claims)
        ):
            raise ValueError(f"{pattern_id}: local_evidence_count 与 source_claims 不一致")
        if claims is not None:
            unknown = sorted(set(source_claims) - set(claims))
            if unknown:
                raise ValueError(f"{pattern_id}: 未知 source_claims: {unknown}")
        for raw in pattern.get("source_raw", []) or []:
            if not (repo_root / raw).exists():
                raise ValueError(f"{pattern_id}: source_raw 不存在: {raw}")
        if not isinstance(pattern.get("drift_flag", []), list):
            raise ValueError(f"{pattern_id}: drift_flag 必须是列表")


def _validate_decision(
    decision: dict,
    doc: dict,
    claims: dict[str, dict],
    repo_root: Path,
    logged: set[str],
) -> None:
    if not isinstance(decision, dict):
        raise ValueError("decision 必须是对象")
    action = decision.get("action")
    if action not in RULE_ACTIONS and action not in STATUS_ACTIONS:
        raise ValueError(f"未知 action: {action}")
    decision_claims = _claims_for(decision, claims, repo_root)
    if action in STATUS_ACTIONS:
        if action in {"rejected", "observing"} and not _norm(decision.get("note")):
            raise ValueError(f"{action} 必须填写 note")
        return

    for claim in decision_claims:
        _source_date(claim)
    patterns = {pattern["pattern_id"]: pattern for pattern in doc["patterns"]}
    pattern_id = decision.get("pattern_id")
    if action != "new_theme" and pattern_id not in patterns:
        raise ValueError(f"未知 pattern_id: {pattern_id}")
    key = _decision_key(decision)

    if action in {"reinforce", "refine", "contradict"}:
        quote = _norm(decision.get("evidence_quote"))
        if not quote or quote not in _norm(decision_claims[0].get("evidence_quote")):
            raise ValueError("evidence_quote 不是 claim 原文的子串")
    if action in {"refine", "contradict"}:
        conflict = _norm(decision.get("conflict_quote"))
        if not conflict:
            raise ValueError("conflict_quote 未命中目标 pattern 原文")
        if key not in logged:
            pattern_text = _norm(_dump_rt(YAML(), patterns[pattern_id]))
            if conflict not in pattern_text:
                raise ValueError("conflict_quote 未命中目标 pattern 原文")
    if action == "refine":
        changes = decision.get("set")
        if not isinstance(changes, dict) or not changes:
            raise ValueError("refine 缺非空 set")
        forbidden = set(changes) - REFINE_FIELDS
        if forbidden:
            raise ValueError(f"禁止修改字段: {sorted(forbidden)}")
    if action == "new_theme":
        candidate = decision.get("candidate_pattern")
        if not isinstance(candidate, dict) or set(candidate) != CANDIDATE_FIELDS:
            raise ValueError(
                f"candidate_pattern 字段必须精确为 {sorted(CANDIDATE_FIELDS)}"
            )
        if not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", str(candidate.get("slug", ""))
        ):
            raise ValueError("candidate_pattern.slug 必须为 kebab-case")
        if len({_source_date(claim) for claim in decision_claims}) < 2:
            raise ValueError("new_theme 至少需要两个不同 source_date")
    if action == "repair_provenance":
        if decision.get("reason") != "broken-source-path":
            raise ValueError("repair_provenance 只接受 broken-source-path")
        if not str(decision.get("provenance", "")).startswith(
            "local-gator-evolution"
        ):
            raise ValueError("repair_provenance 必须写本地 provenance")
        source = patterns[pattern_id].get("source_path")
        if key not in logged and (not source or (repo_root / source).exists()):
            raise ValueError("repair_provenance 要求现有 source_path 已失效")


def _add_evidence(pattern: dict, claims: list[dict]) -> None:
    claim_ids = sorted(
        set(pattern.get("source_claims", []) or []) | {claim["id"] for claim in claims}
    )
    dates = sorted(
        set(pattern.get("source_dates", []) or [])
        | {_source_date(claim) for claim in claims}
    )
    raw = sorted(
        set(pattern.get("source_raw", []) or [])
        | {claim["source_path"] for claim in claims}
    )
    pattern["source_claims"] = claim_ids
    pattern["source_dates"] = dates
    pattern["source_raw"] = raw
    pattern["local_evidence_count"] = len(claim_ids)


def _set_review(
    state: dict,
    claim_ids: list[str],
    status: str,
    proposal_id: str,
    note: str = "",
) -> None:
    review = state.setdefault("review_status", {})
    for claim_id in claim_ids:
        existing = review.get(claim_id) or {}
        if (
            existing.get("status") == status
            and existing.get("proposal_id") == proposal_id
            and existing.get("note", "") == note
        ):
            continue
        review[claim_id] = {
            "status": status,
            "proposal_id": proposal_id,
            "updated_at": _now(),
            "note": note,
        }


def _next_version(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)(-draft)?", str(version))
    if not match:
        raise ValueError(f"不支持的版本格式: {version}")
    return f"{match.group(1)}.{int(match.group(2)) + 1}{match.group(3) or ''}"


def _apply_rule_decision(
    decision: dict,
    doc: dict,
    claims: dict[str, dict],
    repo_root: Path,
) -> dict | None:
    action = decision["action"]
    decision_claims = _claims_for(decision, claims, repo_root)
    patterns = {pattern["pattern_id"]: pattern for pattern in doc["patterns"]}
    pattern_id = decision.get("pattern_id")
    before_pattern = None
    before = None
    if action != "new_theme":
        before_pattern = copy.deepcopy(patterns[pattern_id])
    if action in {"refine", "repair_provenance"}:
        tracked = (
            "source_path",
            "provenance",
            "description",
            "trigger",
            "steps",
            "thresholds",
            "table_rules",
            "falsification",
        )
        before = {
            key: copy.deepcopy(patterns[pattern_id][key])
            for key in tracked
            if key in patterns[pattern_id]
        }

    if action == "new_theme":
        candidate = copy.deepcopy(decision["candidate_pattern"])
        slug = candidate.pop("slug")
        chapter = max(int(pattern["chapter"]) for pattern in doc["patterns"]) + 1
        pattern_id = f"gator-ch{chapter:02d}-{slug}"
        pattern = {
            "pattern_id": pattern_id,
            "school": "gator",
            "name": candidate.pop("name"),
            "chapter": chapter,
            "description": candidate.pop("description"),
            "trigger": candidate.pop("trigger"),
            "steps": candidate.pop("steps"),
            "thresholds": candidate.pop("thresholds"),
            "table_rules": candidate.pop("table_rules"),
            "falsification": candidate.pop("falsification"),
            "computable": candidate.pop("computable"),
            "core": candidate.pop("core"),
            "source_ref": "",
            "source_dates": [],
            "source_raw": [],
            "provenance": "local-gator-evolution",
            "validation": candidate.pop("validation"),
        }
        doc["patterns"].append(pattern)
        patterns[pattern_id] = pattern
        _add_evidence(pattern, decision_claims)
    else:
        pattern = patterns[pattern_id]
        if action == "repair_provenance":
            pattern.pop("source_path", None)
            pattern["provenance"] = decision["provenance"]
            _add_evidence(pattern, decision_claims)
        if action in {"reinforce", "refine"}:
            _add_evidence(pattern, decision_claims)
        if action == "refine":
            for key, value in decision["set"].items():
                pattern[key] = copy.deepcopy(value)
        if action == "contradict":
            claim = decision_claims[0]
            pattern.setdefault("drift_flag", []).append(
                {
                    "claim_id": claim["id"],
                    "source_date": _source_date(claim),
                    "quote": decision["evidence_quote"],
                    "conflict_quote": decision["conflict_quote"],
                    "resolution": "pending",
                }
            )

    if before_pattern is not None and before_pattern == pattern:
        return None
    change = {
        "decision_key": _decision_key(decision),
        "action": action,
        "pattern_id": pattern_id,
        "claim_ids": sorted(claim["id"] for claim in decision_claims),
    }
    if before is not None:
        change["before"] = before
        change["after"] = {
            key: copy.deepcopy(pattern.get(key)) for key in before
        }
    return change


def _diff(label: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{label} (before)",
            tofile=f"{label} (after)",
        )
    )


def apply_gator_evolution(
    proposal_path: Path,
    *,
    patterns_path: Path,
    state_path: Path,
    claims_dir: Path,
    repo_root: Path,
    dry_run: bool = False,
) -> dict:
    proposal_path = Path(proposal_path)
    patterns_path = Path(patterns_path)
    state_path = Path(state_path)
    repo_root = Path(repo_root)
    original_patterns = patterns_path.read_text(encoding="utf-8")
    original_state = state_path.read_text(encoding="utf-8")
    original_proposal = proposal_path.read_text(encoding="utf-8")
    proposal_data = yaml.safe_load(original_proposal)
    if not isinstance(proposal_data, dict):
        raise ValueError("提案必须是对象")
    if proposal_data.get("school") != "gator":
        raise ValueError("提案 school 必须为 gator")
    if proposal_data.get("status") not in {"approved", "applied"}:
        raise ValueError("提案必须为 approved（applied 仅用于幂等重放）")
    if not proposal_data.get("approved_by") or not proposal_data.get("approved_at"):
        raise ValueError("approved 提案缺 approved_by/approved_at")
    if not proposal_data.get("proposal_id"):
        raise ValueError("提案缺 proposal_id")
    decisions = proposal_data.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ValueError("提案缺非空 decisions")

    claims = _claim_map(claims_dir)
    rt, doc = _load_patterns(patterns_path)
    logged = _logged_keys(doc)
    repair_ids = {
        decision.get("pattern_id")
        for decision in decisions
        if isinstance(decision, dict)
        and decision.get("action") == "repair_provenance"
    }
    validate_gator_document(
        doc, repo_root, allow_broken=repair_ids, claims=claims
    )
    for decision in decisions:
        _validate_decision(decision, doc, claims, repo_root, logged)

    state = json.loads(original_state)
    if not isinstance(state, dict):
        raise ValueError("state 必须是 JSON 对象")
    proposal_rt = YAML()
    proposal_rt.width = 4096
    proposal_doc = proposal_rt.load(original_proposal)
    proposal_id = proposal_data["proposal_id"]
    report = {
        "applied": [],
        "skipped": [],
        "changes": [],
        "version": doc.get("version"),
    }
    handled_rule_keys = set(logged)
    for decision in decisions:
        key = _decision_key(decision)
        claim_ids = _decision_claim_ids(decision)
        action = decision["action"]
        if action in STATUS_ACTIONS:
            _set_review(
                state,
                claim_ids,
                STATUS_ACTIONS[action],
                proposal_id,
                decision.get("note", ""),
            )
            report["applied"].append(key)
            continue
        if key in handled_rule_keys:
            _set_review(state, claim_ids, "applied", proposal_id)
            report["skipped"].append(
                {"decision_key": key, "reason": "已写回，仅修复复核状态"}
            )
            continue
        change = _apply_rule_decision(decision, doc, claims, repo_root)
        handled_rule_keys.add(key)
        _set_review(state, claim_ids, "applied", proposal_id)
        if change is None:
            report["skipped"].append(
                {"decision_key": key, "reason": "规则已包含目标内容"}
            )
            continue
        report["changes"].append(change)
        report["applied"].append(key)

    if report["changes"]:
        version = _next_version(doc["version"])
        doc["version"] = version
        doc["updated_at"] = _now()
        if doc.get("evolution_log") is None:
            doc["evolution_log"] = []
        doc.setdefault("evolution_log", []).append(
            {
                "version": version,
                "date": date.today().isoformat(),
                "proposal_id": proposal_id,
                "approved_by": proposal_data["approved_by"],
                "applied_at": _now(),
                "changes": report["changes"],
            }
        )
        report["version"] = version
    validate_gator_document(doc, repo_root, claims=claims)

    proposal_was_applied = proposal_doc.get("status") == "applied"
    if not proposal_was_applied:
        proposal_doc["status"] = "applied"
        proposal_doc["applied_at"] = _now()
    if not proposal_was_applied or not proposal_doc.get("applied_pattern_version"):
        proposal_doc["applied_pattern_version"] = report["version"]
    patterns_text = (
        _dump_rt(rt, doc) if report["changes"] else original_patterns
    )
    state_text = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    proposal_text = _dump_rt(proposal_rt, proposal_doc)
    report["diff"] = (
        _diff(str(patterns_path), original_patterns, patterns_text)
        + _diff(str(state_path), original_state, state_text)
        + _diff(str(proposal_path), original_proposal, proposal_text)
    )
    if not dry_run:
        if patterns_text != original_patterns:
            _atomic_write(patterns_path, patterns_text)
        if state_text != original_state:
            _atomic_write(state_path, state_text)
        if proposal_text != original_proposal:
            _atomic_write(proposal_path, proposal_text)
    return report
