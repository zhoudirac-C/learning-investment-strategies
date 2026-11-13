from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from qing_investment.paths import repo_root


_VALID_TRACKS = {"pre_market", "intraday", "closing"}
_VALID_STATUSES = {"pending_maturity", "scored", "error", "missing"}
_RECORD_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def normalize_day(day: str) -> str:
    if not isinstance(day, str):
        raise ValueError("day must be a canonical YYYY-MM-DD string")
    try:
        parsed = date_type.fromisoformat(day)
    except ValueError as exc:
        raise ValueError("day must be a canonical YYYY-MM-DD string") from exc
    if parsed.isoformat() != day:
        raise ValueError("day must be a canonical YYYY-MM-DD string")
    return day


@contextmanager
def record_directory_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / ".record.lock"
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def resolve_track(trigger: dict) -> str:
    trigger_id = trigger.get("id")
    if trigger_id == "pre_market":
        return "pre_market"
    if trigger_id == "closing_review":
        return "closing"
    return "intraday"


def _validate_record_id(record_id: str) -> str:
    if not isinstance(record_id, str) or not _RECORD_ID_PATTERN.fullmatch(record_id):
        raise ValueError("record_id must be a safe filename component")
    return record_id


def _is_present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _input_hash(input_payload: dict) -> str:
    canonical = json.dumps(
        input_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _data_time_is_scoreable(data_as_of: object, generated_at: object) -> bool:
    data_datetime = _parse_iso_datetime(data_as_of)
    generated_datetime = _parse_iso_datetime(generated_at)
    if data_datetime is None or generated_datetime is None:
        return False
    market_timezone = timezone(timedelta(hours=8))
    if data_datetime.tzinfo is None:
        data_datetime = data_datetime.replace(tzinfo=market_timezone)
    if generated_datetime.tzinfo is None:
        generated_datetime = generated_datetime.replace(tzinfo=market_timezone)
    return data_datetime.astimezone(timezone.utc) <= generated_datetime.astimezone(
        timezone.utc
    )


def _direction_key(item: dict) -> str | None:
    value = item.get("direction_id")
    if not _is_present(value):
        return None
    return str(value).strip()


def _duplicate_direction_keys(items: list[dict]) -> set[str]:
    seen = set()
    duplicates = set()
    for item in items:
        key = _direction_key(item)
        if key is None:
            continue
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return duplicates


def _has_unique_stock_code(value: object) -> bool:
    if value is None:
        return False
    return len(re.findall(r"(?<!\d)\d{6}(?!\d)", str(value))) == 1


def _normalize_polarity(item: dict) -> bool:
    value = item.get("polarity")
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    if normalized not in {"long", "short", "neutral"}:
        return False
    item["polarity"] = normalized
    return True


def _score_direction_items(
    items: list[dict],
    *,
    status_allows_scoring: bool,
    data_as_of: object,
    generated_at: object,
) -> None:
    timing_valid = status_allows_scoring and _data_time_is_scoreable(
        data_as_of, generated_at
    )
    duplicates = _duplicate_direction_keys(items)
    for item in items:
        key = _direction_key(item)
        polarity_valid = _normalize_polarity(item)
        item["score_eligible"] = bool(
            timing_valid
            and key is not None
            and key not in duplicates
            and _has_unique_stock_code(item.get("stock_code"))
            and item.get("horizon") == "T+5"
            and polarity_valid
            and _is_present(item.get("invalidation"))
        )


def _has_any_field(item: dict, fields: tuple[str, ...]) -> bool:
    return any(_is_present(item.get(field)) for field in fields)


def build_record(
    *,
    trigger: dict,
    data_as_of: str,
    input_payload: dict,
    generated_at: str | None = None,
    final_judgment: dict | None = None,
    directions: list[dict] | None = None,
    expert_views: list[dict] | None = None,
    raw_output: str = "",
    status: str = "pending_maturity",
    input_availability: dict | None = None,
    data_version: str | None = None,
    rules_version: str | None = None,
    prompt_version: str | None = None,
    review: dict | None = None,
    citations: dict | list | None = None,
    error: dict | str | None = None,
    record_id: str | None = None,
    supersedes_record_id: str | None = None,
) -> dict:
    if status not in _VALID_STATUSES:
        raise ValueError(f"unsupported record status: {status}")

    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat()
    try:
        generated_datetime = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("generated_at must be an ISO-8601 timestamp") from exc

    frozen_record_id = _validate_record_id(uuid4().hex if record_id is None else record_id)
    if supersedes_record_id == "":
        supersedes_record_id = None
    elif supersedes_record_id is not None:
        _validate_record_id(supersedes_record_id)

    judgment = copy.deepcopy(final_judgment) if final_judgment is not None else {}
    frozen_directions = copy.deepcopy(directions) if directions is not None else []
    frozen_expert_views = copy.deepcopy(expert_views) if expert_views is not None else []
    status_allows_scoring = status not in {"error", "missing"} and (
        review is None
        or (isinstance(review, dict) and review.get("passed") is True)
    )

    _score_direction_items(
        frozen_directions,
        status_allows_scoring=status_allows_scoring,
        data_as_of=data_as_of,
        generated_at=generated_at,
    )
    _score_direction_items(
        frozen_expert_views,
        status_allows_scoring=status_allows_scoring,
        data_as_of=data_as_of,
        generated_at=generated_at,
    )

    judgment["score_eligible"] = bool(
        status_allows_scoring
        and _data_time_is_scoreable(data_as_of, generated_at)
        and _data_time_is_scoreable(judgment.get("data_as_of"), generated_at)
        and _is_present(judgment.get("direction"))
        and judgment.get("horizon") == "T+5"
        and _has_any_field(judgment, ("trigger", "trigger_condition", "trigger_conditions"))
        and _has_any_field(
            judgment,
            ("invalidation", "invalidation_condition", "invalidation_conditions"),
        )
    )

    return {
        "record_id": frozen_record_id,
        "date": generated_datetime.date().isoformat(),
        "track": resolve_track(trigger),
        "generated_at": generated_at,
        "data_as_of": data_as_of,
        "trigger": copy.deepcopy(trigger),
        "input_hash": _input_hash(input_payload),
        "input_availability": copy.deepcopy(input_availability) if input_availability is not None else {},
        "data_version": data_version,
        "rules_version": rules_version,
        "prompt_version": prompt_version,
        "final_judgment": judgment,
        "directions": frozen_directions,
        "expert_views": frozen_expert_views,
        "raw_output": raw_output,
        "review": copy.deepcopy(review),
        "citations": copy.deepcopy(citations),
        "status": status,
        "settlement": None,
        "attribution": None,
        "supersedes_record_id": supersedes_record_id,
        "error": copy.deepcopy(error),
    }


def _storage_root(root: Path | str | None) -> Path:
    if root is not None:
        return Path(root)
    environment_root = os.environ.get("QING_AGENT_VALIDATION_ROOT")
    if environment_root:
        return Path(environment_root)
    return repo_root() / "infra" / "data" / "qing_agent"


def record_path(record: dict, *, root: Path | str | None = None) -> Path:
    record_id = _validate_record_id(record.get("record_id"))
    record_date = record.get("date")
    try:
        parsed_date = date_type.fromisoformat(record_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("record date must be an ISO-8601 date") from exc
    if parsed_date.isoformat() != record_date:
        raise ValueError("record date must be an ISO-8601 date")

    track = record.get("track")
    if track not in _VALID_TRACKS:
        raise ValueError(f"unsupported record track: {track}")

    return _storage_root(root) / record_date / track / f"{record_id}.json"


def _read_existing_record(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _validate_explicit_supersedes(record: dict, path: Path) -> None:
    supersedes_record_id = _validate_record_id(record.get("supersedes_record_id"))
    target_path = path.parent / f"{supersedes_record_id}.json"
    if not target_path.is_file():
        raise ValueError(
            "supersedes_record_id must reference an existing record in the same date/track directory"
        )
    target = _read_existing_record(target_path)
    if target is None:
        raise ValueError("supersedes_record_id target must be a readable JSON record")

    target_generated_at = _parse_iso_datetime(target.get("generated_at"))
    generated_at = _parse_iso_datetime(record.get("generated_at"))
    if target_generated_at is None or generated_at is None:
        raise ValueError("supersedes_record_id generated_at values must be valid ISO-8601")
    try:
        target_is_newer = target_generated_at > generated_at
    except TypeError as exc:
        raise ValueError("supersedes_record_id generated_at values must be comparable") from exc
    if target_is_newer:
        raise ValueError("supersedes_record_id target generated_at must not be newer")
    for candidate_path in path.parent.glob("*.json"):
        if candidate_path == path:
            continue
        candidate = _read_existing_record(candidate_path)
        if candidate and candidate.get("supersedes_record_id") == supersedes_record_id:
            raise ValueError("supersedes_record_id target is already superseded")


def _generated_at_sort_key(path: Path, record: dict) -> tuple[datetime, int, str]:
    generated_at = _parse_iso_datetime(record.get("generated_at"))
    if generated_at is None:
        normalized = datetime.min
    elif generated_at.tzinfo is None:
        normalized = generated_at
    else:
        normalized = generated_at.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        modified_ns = path.stat().st_mtime_ns
    except OSError:
        modified_ns = 0
    return normalized, modified_ns, str(record.get("record_id") or "")


def _find_auto_supersedes(record: dict, path: Path) -> str | None:
    input_hash = record.get("input_hash")
    if not _is_present(input_hash) or not path.parent.is_dir():
        return None

    candidates = []
    for candidate_path in path.parent.glob("*.json"):
        if candidate_path == path or not candidate_path.is_file():
            continue
        candidate = _read_existing_record(candidate_path)
        if candidate is None or candidate.get("input_hash") != input_hash:
            continue
        candidate_id = candidate.get("record_id")
        try:
            _validate_record_id(candidate_id)
        except ValueError:
            continue
        if candidate_path.name != f"{candidate_id}.json":
            continue
        candidates.append((candidate_path, candidate))

    if not candidates:
        return None
    _latest_path, latest = max(
        candidates,
        key=lambda item: _generated_at_sort_key(item[0], item[1]),
    )
    return latest["record_id"]


def save_record(record: dict, *, root: Path | str | None = None) -> Path:
    path = record_path(record, root=root)
    with record_directory_lock(path):
        record_to_save = dict(record)
        supersedes_record_id = record_to_save.get("supersedes_record_id")
        if supersedes_record_id is not None and supersedes_record_id != "":
            _validate_explicit_supersedes(record_to_save, path)
        else:
            record_to_save["supersedes_record_id"] = _find_auto_supersedes(
                record_to_save, path
            )

        serialized = json.dumps(
            record_to_save,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.stem}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return path
