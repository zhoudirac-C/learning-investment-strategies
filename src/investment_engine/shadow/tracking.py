"""方向层 T+5 周度跟踪：聚合 scored predictions 的 due_scores，出周度/累计命中率。

数据流：daily.run → run_maturity 回填 due_scores（方向/个股 T+5 超额 vs 沪深300）
→ 本模块只读聚合，不改写 prediction 文件。毕业线：方向 5 日超额命中率 60%
（见 logs/graduation-2026-08-24.md）。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from investment_engine.shadow.predict import PRED_DIR

GRAD_LINE = 0.6  # 毕业线：方向 5 日超额命中率


def _iso_week(day: str) -> str:
    y, w, _ = date.fromisoformat(day).isocalendar()
    return f"{y}-W{w:02d}"


def _pct(x: float | None) -> str:
    return f"{x * 100:.1f}%" if x is not None else "-"


def collect_scored(pred_dir: Path = PRED_DIR) -> list[dict]:
    """收集所有 scored prediction 的到期评分，标注盘前/收盘轨。坏文件跳过。"""
    rows = []
    if not Path(pred_dir).exists():
        return rows
    for path in sorted(Path(pred_dir).glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if rec.get("status") != "scored" or not rec.get("due_scores"):
            continue
        track = "pre" if path.stem.endswith("-pre") else "close"
        rows.append({"date": rec["date"], "track": track, "due_scores": rec["due_scores"]})
    return rows


def build_tracking(pred_dir: Path = PRED_DIR) -> dict:
    """聚合周度/累计/方向维度的 T+5 超额命中统计。"""
    weeks: dict[tuple[str, str], dict] = {}
    directions: dict[str, dict] = {}
    totals = {"dir_hits": 0, "dir_samples": 0, "stock_hits": 0, "stock_samples": 0}
    for row in collect_scored(pred_dir):
        key = (_iso_week(row["date"]), row["track"])
        w = weeks.setdefault(key, {"dir_hits": 0, "dir_samples": 0,
                                   "stock_hits": 0, "stock_samples": 0})
        ds = row["due_scores"]
        for d in ds.get("direction_details") or []:
            hit = int(bool(d["hit"]))
            w["dir_hits"] += hit
            w["dir_samples"] += 1
            totals["dir_hits"] += hit
            totals["dir_samples"] += 1
            agg = directions.setdefault(d["direction_id"],
                                        {"hits": 0, "samples": 0, "excess_sum": 0.0})
            agg["hits"] += hit
            agg["samples"] += 1
            agg["excess_sum"] += d["dir_ret"] - d["bench_ret"]
        stocks = ds.get("stocks") or {}
        w["stock_hits"] += stocks.get("hits", 0)
        w["stock_samples"] += stocks.get("samples", 0)
        totals["stock_hits"] += stocks.get("hits", 0)
        totals["stock_samples"] += stocks.get("samples", 0)

    totals["dir_hit_rate"] = (totals["dir_hits"] / totals["dir_samples"]
                              if totals["dir_samples"] else None)
    totals["stock_hit_rate"] = (totals["stock_hits"] / totals["stock_samples"]
                                if totals["stock_samples"] else None)
    for agg in directions.values():
        agg["hit_rate"] = agg["hits"] / agg["samples"] if agg["samples"] else None
        agg["avg_excess"] = agg["excess_sum"] / agg["samples"] if agg["samples"] else None
    return {"weeks": weeks, "directions": directions, "totals": totals}


def render_markdown(tracking: dict, *, today: str) -> str:
    """渲染周度跟踪报告（logs/direction-tracking-{today}.md）。"""
    totals = tracking["totals"]
    lines = [
        f"# 方向层 T+5 跟踪（{today}）",
        "",
        f"- 累计方向超额命中率：**{_pct(totals['dir_hit_rate'])}**"
        f"（{totals['dir_hits']}/{totals['dir_samples']}，毕业线 {_pct(GRAD_LINE)}）",
        f"- 累计个股超额命中率：{_pct(totals['stock_hit_rate'])}"
        f"（{totals['stock_hits']}/{totals['stock_samples']}）",
        "- 口径：evals/shadow/predictions 中 status=scored 记录的 due_scores，"
        "T+5 超额 = 方向均收益 - 沪深300 同期收益",
        "",
        "## 逐周明细",
        "",
        "| 周 | 轨 | 方向命中 | 命中率 | 个股命中 | 命中率 |",
        "|---|---|---|---|---|---|",
    ]
    for (week, track), w in sorted(tracking["weeks"].items()):
        dir_rate = w["dir_hits"] / w["dir_samples"] if w["dir_samples"] else None
        stock_rate = w["stock_hits"] / w["stock_samples"] if w["stock_samples"] else None
        lines.append(
            f"| {week} | {track} | {w['dir_hits']}/{w['dir_samples']} | {_pct(dir_rate)}"
            f" | {w['stock_hits']}/{w['stock_samples']} | {_pct(stock_rate)} |")

    lines += ["", "## 方向维度（累计，命中率升序）", "",
              "| 方向 | 命中/样本 | 命中率 | 平均超额 |", "|---|---|---|---|---|"]
    ranked = sorted(tracking["directions"].items(),
                    key=lambda kv: (kv[1]["hit_rate"] if kv[1]["hit_rate"] is not None else 1,
                                    -kv[1]["samples"]))
    for direction_id, agg in ranked:
        lines.append(
            f"| {direction_id} | {agg['hits']}/{agg['samples']} | {_pct(agg['hit_rate'])}"
            f" | {_pct(agg['avg_excess'])} |")
    lines.append("")
    return "\n".join(lines)


def render_summary(tracking: dict) -> str:
    """一行摘要（cron 投递用）。"""
    totals = tracking["totals"]
    parts = [f"方向 T+5 累计 {_pct(totals['dir_hit_rate'])}"
             f"（{totals['dir_hits']}/{totals['dir_samples']}，毕业线 {_pct(GRAD_LINE)}）"]
    week_keys = sorted({k[0] for k in tracking["weeks"]})
    if week_keys:
        latest = week_keys[-1]
        for track in ("pre", "close"):
            w = tracking["weeks"].get((latest, track))
            if w and w["dir_samples"]:
                parts.append(f"本周 {track} {w['dir_hits']}/{w['dir_samples']}")
    worst = [d for d, a in tracking["directions"].items()
             if a["samples"] >= 2 and a["hit_rate"] is not None and a["hit_rate"] < GRAD_LINE]
    if worst:
        parts.append("低于毕业线方向：" + "、".join(sorted(worst)))
    return "[direction-tracking] " + "；".join(parts)
