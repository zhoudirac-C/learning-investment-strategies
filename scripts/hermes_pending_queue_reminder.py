#!/usr/bin/env python3
"""产业链待确认队列每日提醒（Hermes cron no_agent watchdog）。

用法（由 ~/.hermes/scripts/qing_pending_queue_reminder.py 包装调度）：
    python scripts/hermes_pending_queue_reminder.py

语义（对齐影子盲判合规监控的静默式告警约定）：
    两个待确认队列全空 → stdout 空（调度层静默，不投递）；
    有积压 → stdout 输出提醒文本，调度层原样投递。
    读取失败（tick 正在写入等）→ 静默退出，次日再报。

环境变量：
    CHAIN_TRACKING_DIR  覆盖 pending JSON 所在目录（默认 infra/data/chain_tracking，测试用）
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKING_DIR = Path(os.environ.get("CHAIN_TRACKING_DIR",
                                   ROOT / "infra" / "data" / "chain_tracking"))

AGE_DAYS = 7          # 演化提案超龄阈值
HIGH_EVIDENCE = 15    # 新链候选高证据阈值


def _load(name: str) -> list[dict]:
    path = TRACKING_DIR / name
    if not path.exists():
        print(f"[pending提醒] 队列文件不存在: {path}", file=sys.stderr)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []  # tick 写入中，本轮静默
    if isinstance(data, dict):
        data = list(data.values())
    return [p for p in data if isinstance(p, dict)]


def main() -> int:
    today = date.today()
    evo = _load("evolution_pending.json")
    prop = _load("proposals_pending.json")
    if not evo and not prop:
        return 0  # 全空 → 静默

    lines = [f"⚠️ 产业链待确认队列提醒（共 {len(evo) + len(prop)} 条）"]

    if evo:
        aged = []
        for p in evo:
            try:
                proposed = date.fromisoformat(str(p.get("proposed_at", "")))
                age = (today - proposed).days
            except ValueError:
                age = 0
            if age > AGE_DAYS:
                aged.append((age, p))
        lines.append(f"【演化提案】{len(evo)} 条待 confirm/reject"
                     + (f"，其中超 {AGE_DAYS} 天 {len(aged)} 条" if aged else ""))
        for age, p in sorted(aged, key=lambda x: -x[0])[:5]:
            lines.append(f"  · {age}天未处理 {p.get('proposal_id')}")
        lines.append("  处理: python scripts/chain_tracker.py evolution list")

    if prop:
        hot = [p for p in prop
               if len(p.get("evidence", []) or []) >= HIGH_EVIDENCE]
        lines.append(f"【新链候选】{len(prop)} 条待确认"
                     + (f"，证据≥{HIGH_EVIDENCE} 共 {len(hot)} 条" if hot else ""))
        for p in sorted(hot, key=lambda x: -len(x.get("evidence", []) or []))[:5]:
            lines.append(f"  · 证据{len(p.get('evidence', []) or [])}条 "
                         f"{p.get('chain_id')}（{p.get('name', '')}）")
        lines.append("  处理: python scripts/chain_discovery.py list")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
