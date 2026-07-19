"""用例 YAML 加载/校验（M1 spec 层）。

schema（实施计划 Task 2 + 全局约束）：
- 必需：``case_id``（非空字符串）、``bars``（非空）、``expect``（mapping）、
  ``claim_refs``（非空列表，每条用例必须挂 claim id）；
- ``expect`` 子键仅允许 fx/bi/seg/zs/bsp，均可选；
- ``claim_refs`` 中每个 id 必须存在于 ``knowledge/claims/*.yaml``
  （扫描所有 ``- id: claim-...`` 行建立全集，模块级缓存只扫一次）。

bars 支持两种写法（委托 builders 转换）：收盘价序列字符串 ``"10,11,9,12,8"``
（自动配默认振幅生成合法 o/h/l/c）或显式 ``[o, h, l, c]`` 行列表；
``ts`` 按 0 起递增补齐，``vol`` 补常量。
expect 保持原始 dict，归一到模型对象是 harness/diff 的职责。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from chan_engine.spec.builders import bars_from
from chan_engine.spec.model import Bar

# src/chan_engine/spec/case_io.py -> 仓根 knowledge/claims/
DEFAULT_CLAIMS_DIR = Path(__file__).resolve().parents[3] / "knowledge" / "claims"

EXPECT_KEYS = ("fx", "bi", "seg", "zs", "bsp")

_CLAIM_ID_RE = re.compile(r"^\s*-\s+id:\s*(claim-\S+)\s*$")

_claim_id_cache: dict[Path, frozenset[str]] = {}


class CaseValidationError(ValueError):
    """用例 YAML schema 或 claim_refs 校验失败。"""


@dataclass
class Case:
    """加载后的用例。``expect`` 为原始 dict（子键是 EXPECT_KEYS 的子集）。"""

    case_id: str
    bars: list[Bar]
    expect: dict[str, Any]
    claim_refs: list[str]


def load_claim_ids(claims_dir: str | Path | None = None) -> frozenset[str]:
    """扫描 claims 目录全部 *.yaml，提取 ``- id: claim-...`` 建立 id 全集。

    按行正则扫描（不做完整 YAML parse），几百个文件一次扫描毫秒级；
    结果按目录做模块级缓存，重复调用返回同一对象。
    """

    root = Path(claims_dir) if claims_dir is not None else DEFAULT_CLAIMS_DIR
    key = root.resolve()
    if key not in _claim_id_cache:
        if not key.is_dir():
            raise CaseValidationError(f"claims 目录不存在: {key}")
        ids: set[str] = set()
        for path in sorted(key.glob("*.yaml")):
            for line in path.read_text(encoding="utf-8").splitlines():
                m = _CLAIM_ID_RE.match(line)
                if m:
                    ids.add(m.group(1))
        _claim_id_cache[key] = frozenset(ids)
    return _claim_id_cache[key]


def clear_claim_id_cache() -> None:
    """清空 claim id 缓存（测试用）。"""

    _claim_id_cache.clear()


def load_case(path: str | Path, claims_dir: str | Path | None = None) -> Case:
    """加载并校验单个用例 YAML。"""

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CaseValidationError(f"用例必须是 YAML mapping: {path}")

    case_id = _require(raw, "case_id")
    if not isinstance(case_id, str) or not case_id:
        raise CaseValidationError("case_id 必须是非空字符串")

    claim_refs = _require(raw, "claim_refs")
    if not isinstance(claim_refs, list) or not claim_refs:
        raise CaseValidationError("claim_refs 必须是非空列表（每条用例必须挂 claim id）")
    _validate_claim_refs(claim_refs, claims_dir)

    bars = _parse_bars(_require(raw, "bars"))

    expect = _require(raw, "expect")
    if not isinstance(expect, dict):
        raise CaseValidationError("expect 必须是 mapping")
    unknown = sorted(set(expect) - set(EXPECT_KEYS))
    if unknown:
        raise CaseValidationError(
            f"expect 含未知子键 {unknown}，仅允许 {list(EXPECT_KEYS)}"
        )

    return Case(case_id=case_id, bars=bars, expect=expect, claim_refs=list(claim_refs))


def _require(raw: dict[str, Any], name: str) -> Any:
    if name not in raw:
        raise CaseValidationError(f"缺少必需字段: {name}")
    return raw[name]


def _validate_claim_refs(
    claim_refs: list[Any], claims_dir: str | Path | None
) -> None:
    if not all(isinstance(r, str) for r in claim_refs):
        raise CaseValidationError("claim_refs 元素必须是字符串")
    known = load_claim_ids(claims_dir)
    missing = [r for r in claim_refs if r not in known]
    if missing:
        raise CaseValidationError(f"claim_refs 含不存在的 claim id: {missing}")


def _parse_bars(raw: Any) -> list[Bar]:
    if not isinstance(raw, (str, list)) or not raw:
        raise CaseValidationError("bars 必须是非空列表或收盘价序列字符串")
    try:
        return bars_from(raw)
    except ValueError as e:
        raise CaseValidationError(f"bars 非法: {e}") from e
