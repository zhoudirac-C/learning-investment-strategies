"""提议持久化与人工确认流程（T20/T21）。

存储布局（与任务书差异见 docs/tasks/m0-chain-phase3-plan.md 决策 1）：
- `infra/data/chain_tracking/proposals_pending.json`：待确认提议（机器域正本）
- `infra/data/chain_tracking/proposals_<date>.json`：日产出审计（任务书 §3.3 指定）

人工确认（confirm）= 把提议转成 schema 合法的
`knowledge/industry-chains/<chain_id>/chain.yaml`——跟踪引擎下一 tick 自动纳入，
即任务书"proposed → active"的 operational 实现。registry 保持无代码读写。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

_CODE_RE = re.compile(r"^(\d{6})")

_SEGMENT_KEYS = (("upstream", "上游"), ("midstream", "中游"), ("downstream", "下游"))


def default_pending_path() -> Path:
    from investment_engine.chain_tracker.report import default_tracking_dir

    return default_tracking_dir() / "proposals_pending.json"


def load_pending(path: Path | str | None = None) -> list[dict]:
    path = Path(path) if path else default_pending_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save_pending(proposals: list[dict], path: Path | str | None = None) -> Path:
    path = Path(path) if path else default_pending_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposals, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return path


def upsert_pending(new_proposals: list[dict], *, path: Path | str | None = None,
                   now: datetime | None = None) -> list[dict]:
    """按 chain_id 去重追加；返回实际新增的提议（已自动补 proposed_at）。"""
    pending = load_pending(path)
    known = {p.get("chain_id") for p in pending}
    today = (now or datetime.now()).date().isoformat()
    added: list[dict] = []
    for p in new_proposals:
        if p.get("chain_id") in known:
            continue
        entry = dict(p)
        entry.setdefault("proposed_at", today)
        pending.append(entry)
        known.add(entry.get("chain_id"))
        added.append(entry)
    if added:
        save_pending(pending, path)
    return added


def append_daily_audit(tracking_dir: Path | str, date: str,
                       proposals: list[dict], *, tick_label: str) -> Path | None:
    """日产出审计：proposals_<date>.json，同日内多次 tick 合并；空则静默。"""
    if not proposals:
        return None
    path = Path(tracking_dir) / f"proposals_{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            existing = data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            existing = []
    existing.extend({**p, "tick": tick_label} for p in proposals)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return path


def _proposal_to_chain(p: dict, *, today: str) -> dict:
    """提议 → schema 合法的 chain dict。坏代码 mapping 跳过（诚实留空）。

    阶段一律从 阶段0-观察 起步（"加入观察列表"语义）：提议只证明"值得关注"，
    阶段推进交给跟踪引擎逐 tick 依据真实信息完成；LLM 初判阶段记入 stage_evidence。
    """
    chain_spec = p.get("chain") if isinstance(p.get("chain"), dict) else {}
    segments: list[dict] = []
    mappings: list[dict] = []
    tracking_metrics: list[dict] = []

    for key, label in _SEGMENT_KEYS:
        seg = chain_spec.get(key) or {}
        if not isinstance(seg, dict):
            seg = {}
        segments.append({
            "id": key,
            "name": label,
            "materials": [str(m) for m in seg.get("materials") or []],
        })
        for kn in seg.get("key_nodes") or []:
            if not isinstance(kn, dict) or not kn.get("node"):
                continue
            tracking_metrics.append({
                "metric": str(kn["node"]),
                "current": kn.get("current"),
                "signal_direction": kn.get("signal"),
            })
        for s in seg.get("stocks") or []:
            if not isinstance(s, dict):
                continue
            m = _CODE_RE.match(str(s.get("code") or "").strip())
            name = str(s.get("name") or "").strip()
            if not m or not name:
                continue  # 非 6 位代码/无名：跳过该标的，不阻断整条链
            mappings.append({
                "code": m.group(1),
                "name": name,
                "segment": key,
                "relation": str(s.get("role") or "标的"),
                "elasticity": "concept",  # 新提议未经验证，保守标 concept
            })

    ev_count = len(p.get("evidence") or [])
    llm_stage = p.get("current_stage") or "阶段0-观察"
    return {
        "chain_id": p["chain_id"],
        "name": p["name"],
        "thesis": p["thesis"],
        "last_verified": today,
        "segments": segments,
        "mappings": mappings,
        "current_stage": "阶段0-观察",
        "stage_confidence": "低",
        "stage_evidence": (f"{today} 人工确认入观察列表；提议于 "
                           f"{p.get('proposed_at') or '未知'}，LLM 初判 {llm_stage}"
                           f"（{p.get('source') or '未知来源'}），积累证据 {ev_count} 条"),
        "timing": {"current_recommendation": p.get("timing"),
                   "next_trigger": None, "risk": None},
        "tracking_metrics": tracking_metrics,
        "falsification": [],  # 待人工补全
    }


def attach_evidence(matches: dict[str, list[dict]], *,
                    path: Path | str | None = None, date: str,
                    max_evidence: int = 50) -> int:
    """把命中待确认提议的信息追加为证据（按 info_id 去重）；返回追加条数。

    证据累积语义（2026-08-31 用户确认）：提议不急着 confirm/reject，
    在候选池里躺一段时间，每个 tick 把命中的新信息挂为证据；
    证据够了人工再 confirm 进观察列表。
    """
    if not matches:
        return 0
    pending = load_pending(path)
    by_id = {p.get("chain_id"): p for p in pending}
    added = 0
    for cid, items in matches.items():
        entry = by_id.get(cid)
        if entry is None:
            continue
        ev = entry.setdefault("evidence", [])
        have = {e.get("info_id") for e in ev if isinstance(e, dict)}
        for it in items:
            if it["info_id"] in have:
                continue
            ev.append({"date": date, "info_id": it["info_id"],
                       "title": it.get("title"), "source": it.get("source")})
            added += 1
        del ev[:-max_evidence]  # 只留最近 N 条，防无限膨胀
        entry["last_evidence_at"] = date
    if added:
        save_pending(pending, path)
    return added


def confirm_proposal(chain_id: str, *, pending_path: Path | str | None = None,
                     base_dir: Path | None = None,
                     today: str | None = None) -> Path:
    """人工确认：提议 → chain.yaml（schema 强校验）；从 pending 移除。返回写入路径。"""
    from investment_engine.industry_chain import store

    pending = load_pending(pending_path)
    entry = next((p for p in pending if p.get("chain_id") == chain_id), None)
    if entry is None:
        raise ValueError(f"待确认提议中不存在: {chain_id!r}")
    if chain_id in store.list_chains(base_dir=base_dir):
        raise ValueError(f"产业链已存在（chain.yaml 已建立）: {chain_id!r}")

    today = today or datetime.now().date().isoformat()
    path = store.save_chain(_proposal_to_chain(entry, today=today),
                            base_dir=base_dir)
    save_pending([p for p in pending if p.get("chain_id") != chain_id],
                 pending_path)
    return path


def reject_proposal(chain_id: str, *,
                    pending_path: Path | str | None = None) -> dict:
    """人工否决：从 pending 移除并返回被移除的提议。"""
    pending = load_pending(pending_path)
    entry = next((p for p in pending if p.get("chain_id") == chain_id), None)
    if entry is None:
        raise ValueError(f"待确认提议中不存在: {chain_id!r}")
    save_pending([p for p in pending if p.get("chain_id") != chain_id],
                 pending_path)
    return entry
