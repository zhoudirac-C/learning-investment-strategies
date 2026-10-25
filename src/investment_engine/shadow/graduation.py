"""毕业判分：滚动 8 周窗口聚合 shadow 双轨指标，对照主计划 10.4 毕业线。

口径：跨日聚合分子分母（非日均值），与 M1 基线一致；窗口按 ISO 自然周
周一锚定；第三判据（路径 A 假设证伪率）v1 可计算口径见
docs/superpowers/specs/2026-10-25-criterion3-computable-definition.md。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from investment_engine.claim_buckets import load_claims

PRED_DIR = Path("evals/shadow/predictions")
CLAIMS_DIR = Path("knowledge/claims")
STAGE_LINE = 0.70
DIRECTION_LINE = 0.60
C3_MARGIN = 0.10  # 判据 3 容差：agent 证伪率 ≤ 历史基准 +10pct
DEFAULT_WEEKS = 8

VERDICT_NO_DATA = "no_data"
VERDICT_INSUFFICIENT = "insufficient_data"
VERDICT_GRADUATED = "graduated"
VERDICT_NOT_YET = "not_yet"

CRITERION3_SPEC = ("docs/superpowers/specs/"
                   "2026-10-25-criterion3-computable-definition.md")
CRITERION3_NOTES = [
    "第三判据 v1 口径（2026-10-25 定义，spec "
    f"{CRITERION3_SPEC}）：",
    "  - 假设载体 = shadow 方向（每条必带失效条件）；证伪 = 市场结算 miss"
    "（5 日超额口径，与 M3 回写一致）；v1 不区分路径 A/B。",
    "  - 历史基准 = up 桶全历史已结算证伪率（带 direction 的 claim，"
    "miss/(hit+miss)，neutral/pending/insufficient 不入分母）。",
    "  - 市场结算口径 ≠ 框架原义置信度口径；路径细分待 shadow 输出 path 字段（v2）。",
]


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


def load_baseline(claims_dir=CLAIMS_DIR) -> dict:
    """历史基准：up 桶全历史已结算证伪率（带 direction 的 claim，hit/miss 口径）。"""
    claims, _skipped = load_claims(Path(claims_dir))
    hit = miss = 0
    for c in claims:
        if c.get("bucket") != "up" or not c.get("direction"):
            continue
        result = (c.get("outcome") or {}).get("result")
        if result == "hit":
            hit += 1
        elif result == "miss":
            miss += 1
    n = hit + miss
    return {"hit": hit, "miss": miss, "n": n,
            "falsification": miss / n if n else None}


def criterion3(direction_stats: dict, baseline: dict) -> dict:
    """判据 3：agent 证伪率（= 1 − 方向命中率）≤ 基准证伪率 +10pct。

    任一侧 n=0 → passed=None（数据不足，judge 据此阻断 graduated）。
    """
    rate, n = direction_stats["rate"], direction_stats["n"]
    agent = (1 - rate) if (n and rate is not None) else None
    base = baseline.get("falsification")
    threshold = base + C3_MARGIN if base is not None else None
    passed = None
    if agent is not None and threshold is not None:
        passed = agent <= threshold
    return {"agent_falsification": agent, "n": n,
            "baseline_falsification": base, "baseline_n": baseline.get("n"),
            "threshold": threshold, "passed": passed}


def weekly_breakdown(records: list[dict]) -> list[dict]:
    """分周明细，按周一起始日升序。"""
    by_week: dict[date, list[dict]] = {}
    for r in records:
        by_week.setdefault(_monday(date.fromisoformat(r["date"])), []).append(r)
    return [{"week_start": ws, **aggregate(rs)}
            for ws, rs in sorted(by_week.items())]


def judge(stats: dict, *, weeks: int, covered_weeks: int,
          c3_passed: bool | None) -> str:
    """按序判定：no_data → insufficient_data → graduated / not_yet。

    graduated 需三项全过（主计划 10.4）；c3_passed 非 True（含数据不足
    None）一律阻断 graduated。
    """
    if stats["stage"]["n"] == 0 and stats["direction"]["n"] == 0:
        return VERDICT_NO_DATA
    if covered_weeks < weeks:
        return VERDICT_INSUFFICIENT
    stage_ok = (stats["stage"]["rate"] or 0) >= STAGE_LINE
    dir_ok = (stats["direction"]["rate"] or 0) >= DIRECTION_LINE
    if stage_ok and dir_ok and c3_passed is True:
        return VERDICT_GRADUATED
    return VERDICT_NOT_YET


def _fmt(m: dict) -> str:
    return "n=0" if m["n"] == 0 else f"{m['rate']:.1%}（n={m['n']}）"


def version_spans(records: list[dict]) -> str:
    """prompt_version 分布（老记录无字段计 v1）。"""
    spans: dict[str, list[str]] = {}
    for r in records:
        spans.setdefault(r.get("prompt_version") or "v1", []).append(r["date"])
    return "；".join(f"{ver}: {min(ds)}~{max(ds)}（{len(ds)} 条）"
                     for ver, ds in sorted(spans.items()))


def _fmt_c3_summary(c3: dict | None) -> str:
    """判据 3 摘要行（报告头部）。"""
    if c3 is None or c3["passed"] is None:
        n = c3["n"] if c3 else 0
        base_n = c3["baseline_n"] if c3 else 0
        return (f"第三判据（路径 A 假设证伪率 ≤ 历史基准 +{C3_MARGIN:.0%}）: "
                f"数据不足（agent n={n}，基准 n={base_n}），不参与本次判定")
    agent = f"{c3['agent_falsification']:.1%}（n={c3['n']}）"
    base = (f"{c3['baseline_falsification']:.1%}（n={c3['baseline_n']}）")
    word = "达标" if c3["passed"] else "不达标"
    return (f"第三判据（路径 A 假设证伪率 ≤ 历史基准 +{C3_MARGIN:.0%}）: "
            f"agent {agent} vs 历史基准 {base} → 阈值 "
            f"{c3['threshold']:.1%}，{word}")


def render_report(*, run_date: date, weeks: int, window_start: date,
                  stats: dict, weekly: list[dict], verdict: str,
                  skipped: int, version_note: str,
                  c3: dict | None = None) -> str:
    lines = [
        f"# 毕业判定报告（{run_date}）",
        "",
        f"- 窗口: 最近 {weeks} 个自然周（{window_start} 起），覆盖 {len(weekly)} 周",
        f"- 阶段一致率: {_fmt(stats['stage'])}（毕业线 {STAGE_LINE:.0%}）",
        f"- 方向 5 日超额命中率: {_fmt(stats['direction'])}（毕业线 {DIRECTION_LINE:.0%}）",
        f"- {_fmt_c3_summary(c3)}",
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
        *[f"- {note}" for note in CRITERION3_NOTES],
        "- 口径: 影子双轨每日盲判数据（非 M1 历史回放）；跨日聚合分子分母，非日均值。",
        f"- prompt 版本: {version_note}（v2=2026-08-11 契约升级；混窗期统计不自动切分，人读分段）",
        f"- 解析跳过 {skipped} 条（坏 JSON 或缺 date）。",
    ]
    return "\n".join(lines) + "\n"


def run(pred_dir=PRED_DIR, *, weeks: int = DEFAULT_WEEKS,
        out_dir=Path("logs"), today: date | None = None,
        claims_dir: Path | None = None) -> Path:
    """组合入口：读 → 窗口 → 聚合 → 判据 3 → 判定 → 写 logs/graduation-<run_date>.md。

    claims_dir=None 时判据 3 按数据不足处理（不读 claims 库）。
    """
    run_date = today or date.today()
    records, skipped = load_records(pred_dir)
    win = window_records(records, weeks=weeks, today=run_date)
    stats = aggregate(win)
    weekly = weekly_breakdown(win)
    c3 = (criterion3(stats["direction"], load_baseline(claims_dir))
          if claims_dir is not None else None)
    verdict = judge(stats, weeks=weeks, covered_weeks=len(weekly),
                    c3_passed=c3["passed"] if c3 else None)
    window_start = _monday(run_date) - timedelta(weeks=weeks - 1)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"graduation-{run_date.isoformat()}.md"
    path.write_text(render_report(run_date=run_date, weeks=weeks,
                                  window_start=window_start, stats=stats,
                                  weekly=weekly, verdict=verdict,
                                  skipped=skipped,
                                  version_note=version_spans(records), c3=c3),
                    encoding="utf-8")
    return path
