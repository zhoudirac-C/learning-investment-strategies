"""毕业判分：滚动 8 周窗口聚合 shadow 双轨指标，对照主计划 10.4 毕业线。

口径：跨日聚合分子分母（非日均值），与 M1 基线一致；窗口按 ISO 自然周
周一锚定；第三判据（假设证伪率）仓库中无可计算定义，本版本不参与判定。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

PRED_DIR = Path("evals/shadow/predictions")
STAGE_LINE = 0.70
DIRECTION_LINE = 0.60
DEFAULT_WEEKS = 8

VERDICT_NO_DATA = "no_data"
VERDICT_INSUFFICIENT = "insufficient_data"
VERDICT_GRADUATED = "graduated"
VERDICT_NOT_YET = "not_yet"

CRITERION3_NOTE = (
    "第三判据（路径 A 假设证伪率 ≤ 历史基准 +10pct）：仓库中无可计算定义"
    "（待 M3 claims 分桶落地后定义），本版本不参与判定。"
)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def load_records(pred_dir) -> tuple[list[dict], int]:
    """读 predictions 目录；返回 (有效记录, 跳过条数)。目录不存在按空处理。"""
    records, skipped = [], 0
    pred_dir = Path(pred_dir)
    if not pred_dir.exists():
        return records, skipped
    for path in sorted(pred_dir.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped += 1
            continue
        if not rec.get("date"):
            skipped += 1
            continue
        records.append(rec)
    return records, skipped


def window_records(records: list[dict], *, weeks: int, today: date) -> list[dict]:
    """最近 weeks 个 ISO 自然周（含 today 所在周）内的记录。"""
    start = _monday(today) - timedelta(weeks=weeks - 1)
    return [r for r in records
            if _monday(date.fromisoformat(r["date"])) >= start]


def aggregate(records: list[dict]) -> dict:
    """两项指标跨日聚合；各自取 n（stage 次日可判，direction 需 5 交易日结算）。"""
    stage_hits = stage_n = 0
    dir_hits = dir_n = 0
    for r in records:
        hit = r.get("stage_hit")
        if hit is not None:
            stage_n += 1
            stage_hits += int(bool(hit))
        if r.get("status") == "scored":
            dirs = (r.get("due_scores") or {}).get("directions") or {}
            dir_n += dirs.get("samples", 0)
            dir_hits += dirs.get("hits", 0)
    return {
        "stage": {"rate": stage_hits / stage_n if stage_n else None, "n": stage_n},
        "direction": {"rate": dir_hits / dir_n if dir_n else None, "n": dir_n},
    }


def weekly_breakdown(records: list[dict]) -> list[dict]:
    """分周明细，按周一起始日升序。"""
    by_week: dict[date, list[dict]] = {}
    for r in records:
        by_week.setdefault(_monday(date.fromisoformat(r["date"])), []).append(r)
    return [{"week_start": ws, **aggregate(rs)}
            for ws, rs in sorted(by_week.items())]


def judge(stats: dict, *, weeks: int, covered_weeks: int) -> str:
    """按序判定：no_data → insufficient_data → graduated / not_yet。"""
    if stats["stage"]["n"] == 0 and stats["direction"]["n"] == 0:
        return VERDICT_NO_DATA
    if covered_weeks < weeks:
        return VERDICT_INSUFFICIENT
    stage_ok = (stats["stage"]["rate"] or 0) >= STAGE_LINE
    dir_ok = (stats["direction"]["rate"] or 0) >= DIRECTION_LINE
    return VERDICT_GRADUATED if (stage_ok and dir_ok) else VERDICT_NOT_YET


def _fmt(m: dict) -> str:
    return "n=0" if m["n"] == 0 else f"{m['rate']:.1%}（n={m['n']}）"


def version_spans(records: list[dict]) -> str:
    """prompt_version 分布（老记录无字段计 v1）。"""
    spans: dict[str, list[str]] = {}
    for r in records:
        spans.setdefault(r.get("prompt_version") or "v1", []).append(r["date"])
    return "；".join(f"{ver}: {min(ds)}~{max(ds)}（{len(ds)} 条）"
                     for ver, ds in sorted(spans.items()))


def render_report(*, run_date: date, weeks: int, window_start: date,
                  stats: dict, weekly: list[dict], verdict: str,
                  skipped: int, version_note: str) -> str:
    lines = [
        f"# 毕业判定报告（{run_date}）",
        "",
        f"- 窗口: 最近 {weeks} 个自然周（{window_start} 起），覆盖 {len(weekly)} 周",
        f"- 阶段一致率: {_fmt(stats['stage'])}（毕业线 {STAGE_LINE:.0%}）",
        f"- 方向 5 日超额命中率: {_fmt(stats['direction'])}（毕业线 {DIRECTION_LINE:.0%}）",
        f"- **verdict: {verdict}**",
        "",
        "## 分周明细",
        "",
        "| 周起始 | 阶段一致率 | 方向超额 |",
        "|---|---|---|",
    ]
    for w in weekly:
        lines.append(
            f"| {w['week_start']} | {_fmt(w['stage'])} | {_fmt(w['direction'])} |")
    lines += [
        "",
        "## 说明",
        "",
        f"- {CRITERION3_NOTE}",
        "- 口径: 影子双轨每日盲判数据（非 M1 历史回放）；跨日聚合分子分母，非日均值。",
        f"- prompt 版本: {version_note}（v2=2026-08-11 契约升级；混窗期统计不自动切分，人读分段）",
        f"- 解析跳过 {skipped} 条（坏 JSON 或缺 date）。",
    ]
    return "\n".join(lines) + "\n"


def run(pred_dir=PRED_DIR, *, weeks: int = DEFAULT_WEEKS,
        out_dir=Path("logs"), today: date | None = None) -> Path:
    """组合入口：读 → 窗口 → 聚合 → 判定 → 写 logs/graduation-<run_date>.md。"""
    run_date = today or date.today()
    records, skipped = load_records(pred_dir)
    win = window_records(records, weeks=weeks, today=run_date)
    stats = aggregate(win)
    weekly = weekly_breakdown(win)
    verdict = judge(stats, weeks=weeks, covered_weeks=len(weekly))
    window_start = _monday(run_date) - timedelta(weeks=weeks - 1)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"graduation-{run_date.isoformat()}.md"
    path.write_text(render_report(run_date=run_date, weeks=weeks,
                                  window_start=window_start, stats=stats,
                                  weekly=weekly, verdict=verdict,
                                  skipped=skipped,
                                  version_note=version_spans(records)),
                    encoding="utf-8")
    return path
