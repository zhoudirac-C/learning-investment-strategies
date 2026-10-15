"""学派冲突登记表加载（辩论卡）。

设计文档：docs/design/dual-school-architecture.md §5.3 / §5.4
数据：framework/school-conflicts.yaml

核心纪律（2026-10-15 用户拍板）：
- 冲突不做回测裁决，作为多专家不同观点**长期并列保留**
- standing 状态的冲突，输出必须双列，不允许 agent 选边或调和
- resolution 仅来自用户人工裁决，不由此模块生成
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
CONFLICTS_FILE = _REPO_ROOT / "framework" / "school-conflicts.yaml"

# 需要 agent 双列输出（禁止选边）的状态：
# standing = 长期并列（默认）；backtesting 保留以兼容历史数据
UNRESOLVED_STATUSES = {"standing", "backtesting"}


@dataclass
class SchoolConflict:
    """一条学派冲突（辩论卡）。"""

    conflict_id: str
    question: str
    theme: str = ""
    severity: str = "medium"
    school_views: dict = field(default_factory=dict)
    round1_cross_exam: dict = field(default_factory=dict)
    status: str = "standing"
    resolution: dict | None = None

    @property
    def is_unresolved(self) -> bool:
        """长期并列/未裁决 → agent 必须双列呈现，不得选边。"""
        return self.status in UNRESOLVED_STATUSES

    def render_card(self) -> str:
        """渲染为 agent 可读的辩论卡文本。"""
        lines = [f"【{self.conflict_id}】{self.question}（主题：{self.theme}）"]
        for school, v in (self.school_views or {}).items():
            if isinstance(v, dict):
                lines.append(f"  · {school} 视角：{v.get('view','')}")
                if v.get("evidence"):
                    lines.append(f"    依据：{', '.join(str(e) for e in v['evidence'])}")
            else:
                lines.append(f"  · {school} 视角：{v}")
        exam = self.round1_cross_exam or {}
        if exam.get("qing_critique"):
            lines.append(f"  · 交叉反驳（对 qing）：{exam['qing_critique']}")
        if exam.get("gator_critique"):
            lines.append(f"  · 交叉反驳（对 gator）：{exam['gator_critique']}")
        if self.is_unresolved:
            lines.append("  ⚠️ 状态：多专家分歧，长期并列 —— 必须双列呈现，不得自行选边或调和")
        elif self.resolution:
            lines.append(f"  ✅ 裁决：{self.resolution}")
        return "\n".join(lines)


def load_conflicts(path: Path | None = None) -> list[SchoolConflict]:
    """加载全部冲突登记。文件缺失/损坏时返回空列表（不阻断主流程）。"""
    f = path or CONFLICTS_FILE
    if not f.exists():
        return []
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    out: list[SchoolConflict] = []
    for c in data.get("conflicts", []) or []:
        if not isinstance(c, dict) or not c.get("conflict_id"):
            continue
        out.append(
            SchoolConflict(
                conflict_id=str(c["conflict_id"]),
                question=c.get("question", ""),
                theme=c.get("theme", ""),
                severity=c.get("severity", "medium"),
                school_views=c.get("school_views", {}) or {},
                round1_cross_exam=c.get("round1_cross_exam", {}) or {},
                status=c.get("status", "standing"),
                resolution=c.get("resolution"),
            )
        )
    return out


def select_relevant(
    conflicts: list[SchoolConflict],
    themes: list[str] | None = None,
    keywords: list[str] | None = None,
    include_unresolved_only: bool = False,
) -> list[SchoolConflict]:
    """按主题/关键词筛选相关冲突，供注入 context。"""
    if include_unresolved_only:
        conflicts = [c for c in conflicts if c.is_unresolved]
    if not themes and not keywords:
        return conflicts
    sel: list[SchoolConflict] = []
    for c in conflicts:
        if themes and c.theme in themes:
            sel.append(c)
            continue
        if keywords:
            blob = f"{c.question} {c.theme}"
            if any(k in blob for k in keywords):
                sel.append(c)
    return sel


def render_conflicts_block(conflicts: list[SchoolConflict]) -> str:
    """渲染冲突块文本（注入 prompt 用）。"""
    if not conflicts:
        return ""
    parts = ["## 学派冲突（辩论卡）"]
    for c in conflicts:
        parts.append(c.render_card())
    return "\n\n".join(parts)


def load_conflicts_block(
    themes: list[str] | None = None,
    keywords: list[str] | None = None,
    unresolved_only: bool = True,
) -> str:
    """便捷入口：加载 + 筛选 + 渲染。"""
    allc = load_conflicts()
    sel = select_relevant(allc, themes, keywords, include_unresolved_only=unresolved_only)
    return render_conflicts_block(sel)
