"""产业链知识库 chain.yaml 的 schema 校验。

schema 定义见 investment-learning-project/ai-stock-investment-plan.md 第五节。
设计原则：待补字段允许 None（诚实留空），但结构与枚举必须合法。
"""
from __future__ import annotations

import re

ELASTICITY_LEVELS = ("core", "elastic", "concept")

REQUIRED_CHAIN_FIELDS = ("chain_id", "name", "thesis", "segments", "mappings", "last_verified")
REQUIRED_SEGMENT_FIELDS = ("id", "name")
REQUIRED_MAPPING_FIELDS = ("code", "name", "segment", "relation", "elasticity")

# M0-Chain 扩展字段（可选，用于持续跟踪管线）
OPTIONAL_CHAIN_FIELDS = (
    "current_stage",        # 阶段0观察/阶段1启动期/阶段2加速期/阶段3分歧期/阶段4见顶期
    "stage_confidence",     # 高/中/低
    "stage_evidence",        # 阶段判断依据文本
    "timing",                # 时机判断 dict: current_recommendation/next_trigger/risk
    "tracking_metrics",    # 跟踪指标 list: [{metric, current, signal_direction, source}]
    "falsification",         # 证伪条件 list: [str]
    "chain_relations",      # 跨链传导 list: [{target, relation, note}]
    "daily_checks",          # 每日检查 list: [{check, source, frequency, signal}]
    "history",                # 历史记录 list: [{date, stage, action, result}]
)

STAGE_LEVELS = (
    "阶段0-观察", "阶段1-启动期", "阶段2-加速期",
    "阶段3-分歧期", "阶段4-见顶期",
)
CONFIDENCE_LEVELS = ("高", "中", "低")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_CODE_RE = re.compile(r"^\d{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ChainSchemaError(ValueError):
    """chain.yaml 结构或取值不合法。"""


def _check_date(value, where: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not _DATE_RE.match(value):
        errors.append(f"{where}: 日期必须为 'YYYY-MM-DD' 字符串，得到 {value!r}")


def validate_chain(data: dict) -> dict:
    """校验 chain.yaml 解码后的 dict。合法原样返回，不合法抛 ChainSchemaError。"""
    if not isinstance(data, dict):
        raise ChainSchemaError("chain.yaml 顶层必须是 mapping")

    errors: list[str] = []
    for field in REQUIRED_CHAIN_FIELDS:
        if field not in data:
            errors.append(f"缺必填字段: {field}")
    if errors:
        raise ChainSchemaError("; ".join(errors))

    if not _SLUG_RE.match(str(data["chain_id"])):
        errors.append(f"chain_id 必须是小写字母/数字/连字符 slug，得到 {data['chain_id']!r}")
    _check_date(data.get("last_verified"), "last_verified", errors)

    segments = data.get("segments") or []
    segment_ids: set[str] = set()
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            errors.append(f"segments[{i}]: 必须是 mapping")
            continue
        for field in REQUIRED_SEGMENT_FIELDS:
            if field not in seg:
                errors.append(f"segments[{i}]: 缺 {field}")
        sid = seg.get("id")
        if sid is not None:
            if not _SLUG_RE.match(str(sid)):
                errors.append(f"segments[{i}].id 必须是 slug，得到 {sid!r}")
            if sid in segment_ids:
                errors.append(f"segments[{i}]: id 重复 {sid!r}")
            segment_ids.add(sid)
        _check_date(seg.get("last_verified"), f"segments[{i}].last_verified", errors)

    for i, m in enumerate(data.get("mappings") or []):
        if not isinstance(m, dict):
            errors.append(f"mappings[{i}]: 必须是 mapping")
            continue
        for field in REQUIRED_MAPPING_FIELDS:
            if field not in m:
                errors.append(f"mappings[{i}]: 缺 {field}")
        code = str(m.get("code", ""))
        if code and not _CODE_RE.match(code):
            errors.append(f"mappings[{i}]: code 必须是 6 位数字字符串，得到 {m.get('code')!r}")
        seg = m.get("segment")
        if seg is not None and seg not in segment_ids:
            errors.append(f"mappings[{i}]: segment {seg!r} 不在 segments 定义中")
        elasticity = m.get("elasticity")
        if elasticity is not None and elasticity not in ELASTICITY_LEVELS:
            errors.append(f"mappings[{i}]: elasticity 必须 ∈ {ELASTICITY_LEVELS}，得到 {elasticity!r}")
        _check_date(m.get("last_verified"), f"mappings[{i}].last_verified", errors)

    # --- M0-Chain 扩展字段校验（可选字段，存在则校验取值） ---
    stage = data.get("current_stage")
    if stage is not None and stage not in STAGE_LEVELS:
        errors.append(f"current_stage 必须 ∈ {STAGE_LEVELS}，得到 {stage!r}")

    conf = data.get("stage_confidence")
    if conf is not None and conf not in CONFIDENCE_LEVELS:
        errors.append(f"stage_confidence 必须 ∈ {CONFIDENCE_LEVELS}，得到 {conf!r}")

    if errors:
        raise ChainSchemaError("; ".join(errors))
    return data
