"""来源中立推理模式的 schema 校验（v2.1 引擎⓪ 的机械保证）。

核心规则：
- 决策字段（trigger/steps[].action/falsification）禁止出现 UP/青枫浦/博主——
  触发条件必须是客观数据特征，不是"谁说了什么"；
- source_raw 保留溯源，不受此限；
- validation 区块三子字段必须存在，historical_hit_rate 允许 null / 数值 / "pending-m1"。
"""
from __future__ import annotations

import re

REQUIRED_FIELDS = (
    "pattern_id", "name", "description", "trigger",
    "data_requirements", "steps", "falsification", "validation",
)
VALIDATION_FIELDS = ("historical_hit_rate", "applicable_regime", "known_failures")
REQUIRED_STEP_FIELDS = ("step", "name", "question", "action")
FORBIDDEN_RE = re.compile(r"UP|青枫浦|博主")


class PatternSchemaError(ValueError):
    """推理模式结构或取值不合法。"""


def _check_neutral(value, where: str, errors: list[str]) -> None:
    texts: list[str] = []
    if isinstance(value, str):
        texts.append(value)
    elif isinstance(value, list):
        texts.extend(str(v) for v in value)
    for t in texts:
        m = FORBIDDEN_RE.search(t)
        if m:
            errors.append(f"{where}: 决策字段必须来源中立，禁止出现 {m.group(0)!r}（{t[:30]}…）")


def validate_pattern(data: dict) -> dict:
    if not isinstance(data, dict):
        raise PatternSchemaError("模式顶层必须是 mapping")

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"缺必填字段: {field}")
    if errors:
        raise PatternSchemaError("; ".join(errors))

    _check_neutral(data.get("trigger"), "trigger", errors)
    _check_neutral(data.get("falsification"), "falsification", errors)

    req_names: set[str] = set()
    for i, req in enumerate(data.get("data_requirements") or []):
        if not isinstance(req, dict) or "name" not in req:
            errors.append(f"data_requirements[{i}]: 缺 name")
            continue
        if not req.get("channel"):
            errors.append(f"data_requirements[{i}] ({req['name']}): 缺 channel")
        req_names.add(req["name"])

    for i, step in enumerate(data.get("steps") or []):
        for field in REQUIRED_STEP_FIELDS:
            if field not in step:
                errors.append(f"steps[{i}]: 缺 {field}")
        _check_neutral(step.get("action", ""), f"steps[{i}].action", errors)
        for ref in step.get("data") or []:
            if ref not in req_names:
                errors.append(f"steps[{i}].data: {ref!r} 不在 data_requirements 中")

    validation = data.get("validation") or {}
    for field in VALIDATION_FIELDS:
        if field not in validation:
            errors.append(f"validation: 缺 {field}")
    rate = validation.get("historical_hit_rate")
    if rate is not None and rate != "pending-m1" and not isinstance(rate, (int, float)):
        errors.append(f"validation.historical_hit_rate 必须是 null / 数值 / 'pending-m1'，得到 {rate!r}")

    if errors:
        raise PatternSchemaError("; ".join(errors))
    return data


def validate_patterns_file(data: dict) -> dict:
    """校验整份 reasoning-patterns.yaml（顶层含 patterns 列表）。"""
    patterns = (data or {}).get("patterns")
    if not isinstance(patterns, list) or not patterns:
        raise PatternSchemaError("patterns 必须是非空列表")
    for p in patterns:
        validate_pattern(p)
    return data
