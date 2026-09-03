"""增量报告输出（T14）。

硬规则：空批次静默——仅有变化的链或有演化提案才写报告；ticks.jsonl 每 tick
一条（机器可读，供复盘与 T16 验证用），不算刷屏。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def default_tracking_dir() -> Path:
    from qing_investment.paths import repo_root

    return repo_root() / "infra" / "data" / "chain_tracking"


def render_changes_section(changes: list[dict], *, tick_label: str) -> str:
    lines = [f"## {tick_label} tick（{len(changes)} 条链有变化）", ""]
    for c in changes:
        lines.append(f"### {c['chain_name']}（{c['chain_id']}）")
        lines.append(f"- 阶段：{c['old_stage']} → **{c['new_stage']}**"
                     f"（{c['stage_change']}，置信度 {c.get('confidence') or '-'}，"
                     f"verdict={c.get('verdict') or '-'}）")
        if c.get("clamped"):
            lines.append(f"- ⚠️ LLM 建议 {c.get('llm_new_stage')}，按护栏截断为相邻阶段")
        if c.get("timing"):
            lines.append(f"- 时机建议：{c['timing']}")
        if c.get("action"):
            lines.append(f"- 操作：{c['action']}")
        if c.get("summary"):
            lines.append(f"- 依据：{c['summary']}")
        if c.get("info_ids"):
            lines.append(f"- 关联信息：{len(c['info_ids'])} 条"
                         f"（{', '.join(c['info_ids'][:5])}）")
        lines.append("")
    return "\n".join(lines)


def render_evolution_section(proposals: list[dict], *, tick_label: str) -> str:
    """演化提案附节：结构性增量提案（阶段无变化时也会写日报）。"""
    lines = [f"## {tick_label} tick 演化提案（{len(proposals)} 条，待人工 confirm）", ""]
    for p in proposals:
        lines.append(f"### {p.get('chain_name') or p.get('chain_id')}"
                     f"（{p.get('chain_id')}）")
        lines.append(f"- [{p.get('change_type')}] {p.get('summary')}"
                     f"（置信度 {p.get('confidence') or '-'}）")
        if p.get("rationale"):
            lines.append(f"- 依据：{p['rationale']}")
        lines.append("- 确认：`python scripts/chain_tracker.py evolution confirm "
                     f"{p.get('proposal_id')}`")
        lines.append("")
    return "\n".join(lines)


def append_daily_report(path: Path | str, changes: list[dict], *,
                        tick_label: str,
                        evolution: list[dict] | None = None) -> Path | None:
    """有阶段变化或有演化提案才写；返回路径或 None（静默）。"""
    evolution = evolution or []
    if not changes and not evolution:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        date = path.stem.replace("daily_report_", "")
        path.write_text(f"# 产业链跟踪日报 {date}\n\n"
                        f"> 记录有状态变化的产业链与逻辑演化提案；"
                        f"全无变化的 tick 静默。\n\n",
                        encoding="utf-8")
    parts = []
    if changes:
        parts.append(render_changes_section(changes, tick_label=tick_label))
    if evolution:
        parts.append(render_evolution_section(evolution, tick_label=tick_label))
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")
    return path


def append_tick_log(path: Path | str, entry: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
