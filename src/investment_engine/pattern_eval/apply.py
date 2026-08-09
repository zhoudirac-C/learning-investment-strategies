"""提案执行器：结构 fail-fast → 当前值守卫（幂等）→ 应用 → 整文件再校验（ruamel 保格式）。"""
from __future__ import annotations

import io
import re
from pathlib import Path

import yaml
from ruamel.yaml import YAML

from investment_engine.distill.pattern_schema import validate_patterns_file

SETTABLE = ("historical_hit_rate", "applicable_regime")


def _guard(pattern: dict, change: dict) -> str | None:
    """返回 None 可应用；否则返回 SKIP 原因（当前值已变化 → 幂等跳过）。

    按 SETTABLE 固定顺序检查，不受提案文件序列化后的键序影响。
    """
    v = pattern.get("validation") or {}
    requested = {key.split(".")[-1] for key in (change.get("set") or {})}
    for field in SETTABLE:
        if field not in requested:
            continue
        if field == "historical_hit_rate" and v.get(field) != "pending-m1":
            return f"historical_hit_rate 当前值 {v.get(field)!r}，非 pending-m1"
        if field == "applicable_regime" and v.get(field) is not None:
            return f"applicable_regime 当前值 {v.get(field)!r}，非 null"
    existing = v.get("known_failures") or []
    for item in change.get("append_known_failures") or []:
        if item in existing:
            return "known_failures 已含该条目"
    return None


def apply_proposal(proposal_path, *, patterns_path, dry_run: bool = False) -> dict:
    """应用提案。结构问题 fail-fast（不部分应用）；守卫不满足的条目 SKIP。"""
    proposal = yaml.safe_load(Path(proposal_path).read_text(encoding="utf-8"))
    patterns_file = Path(patterns_path)
    rt = YAML()  # round-trip 模式，保留未触碰部分的原始格式
    rt.width = 4096  # 禁止折叠长行，避免无关 diff
    doc = rt.load(patterns_file.read_text(encoding="utf-8"))
    validate_patterns_file(doc)  # 应用前整文件校验

    changes = (proposal or {}).get("changes")
    if not isinstance(changes, list):
        raise ValueError("提案缺 changes 列表")
    patterns = {p["pattern_id"]: p for p in doc["patterns"]}
    # pass 1：结构校验，任一非法即整体拒绝
    for ch in changes:
        pid = ch.get("pattern_id")
        if pid not in patterns:
            raise ValueError(f"提案含未知 pattern_id: {pid!r}")
        for key in (ch.get("set") or {}):
            if key.split(".")[-1] not in SETTABLE:
                raise ValueError(f"{pid}: 禁止修改 {key!r}")

    report = {"applied": [], "skipped": []}
    for ch in changes:
        pid = ch["pattern_id"]
        reason = _guard(patterns[pid], ch)
        if reason:
            report["skipped"].append({"pattern_id": pid, "reason": reason})
            continue
        v = patterns[pid].setdefault("validation", {})
        for key, val in (ch.get("set") or {}).items():
            v[key.split(".")[-1]] = val
        for item in ch.get("append_known_failures") or []:
            v.setdefault("known_failures", []).append(item)
        report["applied"].append(pid)

    if not dry_run and report["applied"]:
        validate_patterns_file(doc)  # 应用后整文件校验，失败不落盘
        buf = io.StringIO()
        rt.dump(doc, buf)
        # ruamel dump 会把未触碰的 "applicable_regime: null" 归一成空值键，
        # 还原为显式 null，保证 diff 只含被修改的块（语义等价，纯格式还原）；
        # 负向前瞻排除已写入嵌套映射的被修改块
        text = re.sub(r"^(\s+)applicable_regime:[ \t]*$(?!\n\1[ \t])",
                      r"\1applicable_regime: null", buf.getvalue(),
                      flags=re.MULTILINE)
        patterns_file.write_text(text, encoding="utf-8")
    return report
