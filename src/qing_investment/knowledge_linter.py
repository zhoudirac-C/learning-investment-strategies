from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_MARKERS = ("T" + "BD", "TO" + "DO", "待" + "定", "以后" + "再", "place" + "holder")
EXCLUDED_DIR_NAMES = {".git", ".venv", "venv", "__pycache__", "vendor", "third_party"}


@dataclass(frozen=True)
class LintIssue:
    path: Path
    marker: str
    line_number: int
    line: str


def lint_markdown_placeholders(root: Path) -> list[LintIssue]:
    issues: list[LintIssue] = []
    for path in sorted(root.rglob("*.md")):
        if _should_skip(path):
            continue
        text = path.read_text(encoding="utf-8")
        for idx, line in enumerate(text.splitlines(), start=1):
            for marker in FORBIDDEN_MARKERS:
                if marker in line:
                    issues.append(LintIssue(path=path, marker=marker, line_number=idx, line=line))
    return issues


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDED_DIR_NAMES:
        return True
    if "sources" in parts and "raw" in parts:
        return True
    return "docs" in parts and "superpowers" in parts and "plans" in parts


# ── 学派一致性 lint（2026-10-15 双学派架构）─────────────────────────
# 校验每条 claim 的 up_id 归属学派 与其 source_path 前缀一致，
# 防止 gator 来源被标注成 qing（跨学派污染）。


@dataclass(frozen=True)
class SchoolLintIssue:
    claim_path: Path
    claim_id: str
    up_id: str
    school: str
    source_path: str
    reason: str


def lint_claim_schools(root: Path) -> list[SchoolLintIssue]:
    """扫描 knowledge/claims/*.yaml，校验 up_id ↔ source_path 学派一致性。"""
    import yaml

    from qing_investment.schools import school_of_up, source_path_allowed

    issues: list[SchoolLintIssue] = []
    claims_dir = Path(root) / "knowledge" / "claims"
    if not claims_dir.exists():
        return issues

    for path in sorted(claims_dir.rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # YAML 语法错误由其他校验负责
            continue
        for claim in (data.get("claims", []) if isinstance(data, dict) else data) or []:
            up_id = str(claim.get("up_id", "") or "")
            src = str(claim.get("source_path", "") or "")
            cid = str(claim.get("id", "") or "")
            if not up_id or not src:
                continue
            sid = school_of_up(up_id)
            if sid is None:
                issues.append(
                    SchoolLintIssue(path, cid, up_id, "", src,
                                    f"up_id 未在 config/schools.yaml 登记")
                )
                continue
            if not source_path_allowed(up_id, src):
                issues.append(
                    SchoolLintIssue(path, cid, up_id, sid, src,
                                    f"source_path 前缀不属于学派 {sid} 的允许来源")
                )
    return issues
