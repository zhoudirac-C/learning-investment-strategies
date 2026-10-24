"""影子双轨完整性报告：4 周日历 + 提案 open/closed 统计。"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from investment_engine.shadow.attribute import ATTR_DIR, PROPOSAL_DIR
from investment_engine.shadow.predict import PRED_DIR

STATUS_PATH = Path("logs/shadow-status.md")


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def collect_status(*, pred_dir: Path = PRED_DIR, attr_dir: Path = ATTR_DIR,
                   proposal_dir: Path = PROPOSAL_DIR) -> dict:
    days = []
    complete = 0
    for path in sorted(Path(pred_dir).glob("*.json")):
        rec = _load_json(path)
        if not rec.get("date"):
            continue
        day = rec["date"]
        stage_hit = rec.get("stage_hit")
        needs_attr = stage_hit is False
        has_attr = (Path(attr_dir) / f"{day}.json").exists()
        ok = (not needs_attr) or has_attr
        complete += int(ok)
        days.append({"date": day, "stage_hit": stage_hit, "status": rec.get("status"),
                     "attributed": has_attr, "complete": ok})

    proposals = {"open": 0, "applied": 0, "rejected": 0, "open_files": []}
    if Path(proposal_dir).exists():
        for p in sorted(list(Path(proposal_dir).glob("*.md"))
                        + list(Path(proposal_dir).glob("*.yaml"))):
            text = p.read_text(encoding="utf-8")
            # 只解析 frontmatter，避免正文代码块里的 status: 行误计
            fm = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
            body = fm.group(1) if fm else text
            m = re.search(r"^status:\s*([\w-]+)", body, re.M)
            st = m.group(1) if m else "open"
            proposals[st] = proposals.get(st, 0) + 1
            if st == "open":
                proposals["open_files"].append(p.name)
    return {"days_total": len(days), "days_complete": complete,
            "days": days, "proposals": proposals}


# 已解决状态词（历史裁决用过 applied/merged/implemented/done 多种写法）
RESOLVED_STATUSES = ("applied", "merged", "implemented", "done")


def render_status(stats: dict) -> str:
    p = stats["proposals"]
    resolved = sum(p.get(s, 0) for s in RESOLVED_STATUSES)
    lines = [
        f"# 影子双轨完整性报告（{date.today():%Y-%m-%d}）",
        "",
        f"- 记录日数: {stats['days_total']}，完整: {stats['days_complete']}",
        f"- 提案: open {p['open']} / 已解决 {resolved}"
        f"（applied {p.get('applied', 0)} / merged {p.get('merged', 0)}"
        f" / implemented {p.get('implemented', 0)} / done {p.get('done', 0)}）"
        f" / pending {p.get('pending', 0) + p.get('pending-review', 0)}"
        f" / rejected {p.get('rejected', 0)} / retracted {p.get('retracted', 0)}"
        + (f" / proposed {p.get('proposed', 0)}" if p.get("proposed") else "")
        + (f" / archived {p.get('archived', 0)}" if p.get("archived") else ""),
        "",
        "| 日期 | 阶段判定 | 状态 | 归因 | 完整 |",
        "|---|---|---|---|---|",
    ]
    for d in stats["days"]:
        hit = {True: "对", False: "错", None: "-"}[d["stage_hit"]]
        lines.append(f"| {d['date']} | {hit} | {d['status']} | {'有' if d['attributed'] else '-'} | {'✅' if d['complete'] else '❌'} |")
    if stats["proposals"]["open_files"]:
        lines += ["", "## 待处理提案（open 置顶）", ""]
        lines += [f"- {n}" for n in stats["proposals"]["open_files"]]
    return "\n".join(lines)


def write_status(path: Path = STATUS_PATH, **kw) -> Path:
    stats = collect_status(**kw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_status(stats), encoding="utf-8")
    return path
