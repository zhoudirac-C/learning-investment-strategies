"""UP 命中率画像聚合（M3 交付物②，spec 2026-10-24-m3-outcome-writeback）。

从已结算 claims（带 direction + outcome）聚合：
- 分组：UP × claim_type × source_date 月（另有 UP×claim_type 合计与 UP 总计）
- 指标：hit / miss / neutral / pending / insufficient / hit_rate
  hit_rate = hit / (hit + miss)（neutral/pending/insufficient 不入分子分母；
  hit+miss < MIN_SAMPLE 标「样本不足」）
"""
from __future__ import annotations

from collections import defaultdict

MIN_SAMPLE = 10

_COUNT_KEYS = ("hit", "miss", "neutral", "pending", "insufficient")


def _empty() -> dict:
    return {k: 0 for k in _COUNT_KEYS} | {"hit_rate": None}


def _bump(group: dict, result: str | None) -> None:
    key = {
        "hit": "hit", "miss": "miss", "neutral_window": "neutral",
        "pending_data": "pending", "insufficient_data": "insufficient",
    }.get(result or "")
    if key:
        group[key] += 1


def _finalize(group: dict) -> dict:
    n = group["hit"] + group["miss"]
    group["hit_rate"] = (group["hit"] / n) if n >= MIN_SAMPLE else None
    return group


def aggregate_profile(claims: list[dict]) -> dict:
    """→ {(up, claim_type[, month]): {"total": {...}}}；month 分组单独成键。"""
    stats: dict[tuple, dict] = {}
    for c in claims:
        direction = c.get("direction") or {}
        outcome = c.get("outcome") or {}
        if not outcome or not direction:
            continue
        up = c.get("up_name") or c.get("up_id") or "未知UP"
        ctype = c.get("claim_type") or "unknown"
        month = str(c.get("source_date") or "")[:7] or "????-??"
        result = outcome.get("result")

        for key in ((up, ctype), (up, ctype, month), (up, "ALL"), (up, "ALL", month)):
            if key not in stats:
                stats[key] = {"total": _empty()}
            _bump(stats[key]["total"], result)

    for v in stats.values():
        _finalize(v["total"])
    return stats


def _fmt_rate(group: dict) -> str:
    if group["hit_rate"] is None:
        return "样本不足" if group["hit"] + group["miss"] > 0 else "—"
    return f"{group['hit_rate']:.1%}"


def render_markdown(stats: dict, generated_on: str = "") -> str:
    lines = [
        "# UP 命中率画像（M3 市场结果回写）",
        "",
        f"生成日期: {generated_on}",
        "",
        "口径: hit_rate = hit / (hit + miss)；neutral_window / pending_data / "
        "insufficient_data 不计入；hit+miss < "
        f"{MIN_SAMPLE} 标「样本不足」。窗口: 5 交易日 forward，|收益|≥1% 计 hit/miss。",
        "",
        "## UP × claim_type 合计",
        "",
        "| UP | claim_type | hit | miss | neutral | pending | insufficient | hit_rate |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key, v in sorted(stats.items()):
        if len(key) != 2:
            continue
        up, ctype = key
        if ctype == "ALL":
            continue
        g = v["total"]
        lines.append(
            f"| {up} | {ctype} | {g['hit']} | {g['miss']} | {g['neutral']} | "
            f"{g['pending']} | {g['insufficient']} | {_fmt_rate(g)} |")
    lines += [
        "",
        "## UP 总览",
        "",
        "| UP | hit | miss | neutral | pending | insufficient | hit_rate |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, v in sorted(stats.items()):
        if len(key) != 2:
            continue
        up, ctype = key
        if ctype != "ALL":
            continue
        g = v["total"]
        lines.append(
            f"| {up} | {g['hit']} | {g['miss']} | {g['neutral']} | "
            f"{g['pending']} | {g['insufficient']} | {_fmt_rate(g)} |")
    return "\n".join(lines) + "\n"
