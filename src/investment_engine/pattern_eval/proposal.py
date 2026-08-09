"""渲染 pattern validation 回写提案（人审界面）：evidence 全量留档，changes 只含落库补丁。"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from investment_engine.pattern_eval.bucket import BUCKET_FAIL

PROPOSAL_SOURCE = "m1-blindtest"
ATTRIBUTION_NOTE = (
    "使用归因（同日多模式共用，未隔离单模式贡献）；"
    "分母只含成功解析出该模式的日子，与 M1 总体口径（含无效日）不同"
)


def _build_changes(metrics: dict, buckets: dict, patterns: list[dict]) -> list[dict]:
    current = {p["pattern_id"]: (p.get("validation") or {}) for p in patterns}
    changes = []
    for pid in sorted(metrics):
        m = metrics[pid]
        b = buckets[pid]
        v = current.get(pid)
        kind = b.get("primary_metric")
        if v is None or kind is None:
            continue
        if v.get("historical_hit_rate") != "pending-m1":
            continue  # 已有实测值（如 technical_timing 的 M0 回测 0.5182），不动
        rate = m[kind]["rate"]
        if rate is None:
            continue  # 无可评分样本，无数可写
        change = {
            "pattern_id": pid,
            "set": {
                "validation.historical_hit_rate": round(rate, 4),
                "validation.applicable_regime": (
                    {label: round(rb["rate"], 4)
                     for label, rb in m["regime"].items() if rb["rate"] is not None}
                    or None
                ),
            },
        }
        if b["bucket"] == BUCKET_FAIL:
            change["append_known_failures"] = [
                f"m1 盲测使用归因主指标 {rate:.1%}（n={m[kind]['n']}，"
                f"窗口见提案 evidence），低于 50% 随机线"
            ]
        changes.append(change)
    return changes


def build_proposal(metrics: dict, buckets: dict, patterns: list[dict], *,
                   window: dict) -> dict:
    evidence_metrics = {}
    for pid, b in buckets.items():
        m = metrics.get(pid)
        if m is None:
            evidence_metrics[pid] = {"bucket": b["bucket"], "note": b.get("note")}
        else:
            evidence_metrics[pid] = {
                **m, "primary_metric": b.get("primary_metric"), "bucket": b["bucket"],
            }
    return {
        "proposal_id": f"{dt.date.today():%Y%m%d}-pattern-validation-m1",
        "source": PROPOSAL_SOURCE,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "evidence": {
            "window": window,
            "attribution": ATTRIBUTION_NOTE,
            "metrics": evidence_metrics,
        },
        "changes": _build_changes(metrics, buckets, patterns),
    }


def write_proposal(proposal: dict, out_dir=Path("framework/proposals")) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{proposal['proposal_id']}.yaml"
    path.write_text(yaml.safe_dump(proposal, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return path
