"""学派注册表加载与查询。

唯一的 up_id → school 映射源：config/schools.yaml。

设计文档：docs/design/dual-school-architecture.md
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from qing_investment.paths import repo_root


@dataclass(frozen=True)
class School:
    school_id: str
    display_name: str
    up_ids: tuple[str, ...]
    sources: tuple[str, ...]
    style: str
    is_default: bool
    provenance_note: str = ""


@lru_cache(maxsize=1)
def load_schools() -> tuple[School, ...]:
    """读取 config/schools.yaml（缓存）。"""
    path = Path(repo_root()) / "config" / "schools.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    schools = []
    for item in data.get("schools", []):
        schools.append(
            School(
                school_id=str(item["school_id"]),
                display_name=str(item["display_name"]),
                up_ids=tuple(str(u) for u in item.get("up_ids", [])),
                sources=tuple(str(s) for s in item.get("sources", [])),
                style=str(item.get("style", "")),
                is_default=bool(item.get("is_default", False)),
                provenance_note=str(item.get("provenance_note", "") or ""),
            )
        )
    if not schools:
        raise ValueError("config/schools.yaml 未定义任何学派")
    return tuple(schools)


@lru_cache(maxsize=1)
def _up_to_school() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for s in load_schools():
        for up_id in s.up_ids:
            if up_id in mapping:
                raise ValueError(
                    f"up_id {up_id!r} 同时属于 {mapping[up_id]} 与 {s.school_id}，"
                    "schools.yaml 映射冲突"
                )
            mapping[up_id] = s.school_id
    return mapping


def school_of_up(up_id: str) -> str | None:
    """返回 up_id 所属 school_id；未登记返回 None。"""
    return _up_to_school().get(str(up_id))


def default_school() -> str:
    for s in load_schools():
        if s.is_default:
            return s.school_id
    return load_schools()[0].school_id


def school_sources(school_id: str) -> tuple[str, ...]:
    for s in load_schools():
        if s.school_id == school_id:
            return s.sources
    return ()


def all_school_ids() -> tuple[str, ...]:
    return tuple(s.school_id for s in load_schools())


def source_path_allowed(up_id: str, source_path: str) -> bool:
    """校验 claim 的 source_path 是否在该 up 所属学派的允许来源前缀内。

    未登记的 up_id 返回 True（不阻断，交由其他校验处理）。
    """
    sid = school_of_up(up_id)
    if sid is None:
        return True
    allowed = school_sources(sid)
    if not allowed:
        return True
    return any(str(source_path).startswith(prefix) for prefix in allowed)
