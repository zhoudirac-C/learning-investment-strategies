"""产业链逻辑演化提案（M0-Chain 演化能力）。

设计见 docs/superpowers/specs/2026-08-31-chain-logic-evolution-design.md。

与阶段跟踪的分工：跟踪引擎（state.py）自动更新阶段（走一格护栏）；本模块负责
产业链【逻辑结构】的演化——环节细化 / 新增节点 / 重心转移 / thesis 修正 /
证伪条件更新 / 跨链传导，一律走"LLM 提案 → pending → 人工 confirm 应用"，
不自动改 chain.yaml（对齐发现引擎的人工确认哲学，防幻觉改坏知识库）。

存储布局（与 proposals.py 同构）：
- `infra/data/chain_tracking/evolution_pending.json`：待确认演化提案（机器域正本）
- `infra/data/chain_tracking/evolution_<date>.json`：日产出审计

提案身份：proposal_id = "{chain_id}:{change_type}:{target_key}"（target_key 按
change_type 取标识：add_node→metric名/股票code/股票名，refine_segment→segment_id，
focus_shift→to_segment，update_thesis→thesis，update_falsification→falsification，
add_relation→target）。同 identity 再命中只合并证据，不重复占位（候选池语义）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from investment_engine.industry_chain.schema import CONFIDENCE_LEVELS

CHANGE_TYPES = (
    "refine_segment",       # 环节细化：环节新增材料/拆分新环节
    "add_node",             # 新增关键节点：跟踪指标和/或标的
    "focus_shift",          # 重心转移：受益环节/时机结构性迁移
    "update_thesis",        # 产业逻辑（传导路径本身）修正
    "update_falsification",  # 证伪条件更新
    "add_relation",         # 跨链传导关系
)

_CODE_RE = re.compile(r"^\d{6}$")
_MAX_EVIDENCE = 50  # 与 proposals.attach_evidence 同口径


def default_pending_path() -> Path:
    from investment_engine.chain_tracker.report import default_tracking_dir

    return default_tracking_dir() / "evolution_pending.json"


# ---------------------------------------------------------------- 解析校验

def _target_key(change_type: str, detail: dict) -> str | None:
    """按 change_type 取去重标识；取不到返回 None（提案不合格）。"""
    if change_type == "refine_segment":
        return _as_nonempty_str(detail.get("segment_id"))
    if change_type == "add_node":
        metric = detail.get("metric")
        if isinstance(metric, dict):
            key = _as_nonempty_str(metric.get("metric"))
            if key:
                return key
        stock = detail.get("stock")
        if isinstance(stock, dict):
            return (_as_nonempty_str(stock.get("code"))
                    or _as_nonempty_str(stock.get("name")))
        return None
    if change_type == "focus_shift":
        return _as_nonempty_str(detail.get("to_segment"))
    if change_type == "update_thesis":
        return "thesis"
    if change_type == "update_falsification":
        return "falsification"
    if change_type == "add_relation":
        return _as_nonempty_str(detail.get("target"))
    return None


def _as_nonempty_str(v) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _valid_detail(change_type: str, detail) -> bool:
    """detail 关键字段校验（每类提案的最小可用信息量）。"""
    if not isinstance(detail, dict):
        return False
    if change_type == "refine_segment":
        return _as_nonempty_str(detail.get("segment_id")) is not None
    if change_type == "add_node":
        metric = detail.get("metric")
        stock = detail.get("stock")
        has_metric = (isinstance(metric, dict)
                      and _as_nonempty_str(metric.get("metric")) is not None)
        has_stock = (isinstance(stock, dict)
                     and _as_nonempty_str(stock.get("name")) is not None)
        return has_metric or has_stock
    if change_type == "focus_shift":
        return _as_nonempty_str(detail.get("to_segment")) is not None
    if change_type == "update_thesis":
        return _as_nonempty_str(detail.get("new_thesis")) is not None
    if change_type == "update_falsification":
        add = detail.get("add")
        return isinstance(add, list) and any(
            _as_nonempty_str(x) for x in add)
    if change_type == "add_relation":
        return (_as_nonempty_str(detail.get("target")) is not None
                and _as_nonempty_str(detail.get("relation")) is not None)
    return False


def parse_logic_update(result: dict) -> dict | None:
    """从 analyze_chain 结果提取并校验 logic_update；不合格返回 None（只丢提案）。

    丢弃规则：缺失/null、非 dict、verdict=irrelevant、change_type 非法、
    summary 空、detail 缺关键字段。confidence 归一（非法→"中"）。
    """
    lu = result.get("logic_update")
    if not isinstance(lu, dict):
        return None
    if result.get("verdict") == "irrelevant":
        return None
    change_type = lu.get("change_type")
    if change_type not in CHANGE_TYPES:
        return None
    if not _as_nonempty_str(lu.get("summary")):
        return None
    detail = lu.get("detail")
    if not _valid_detail(change_type, detail):
        return None
    confidence = lu.get("confidence")
    return {
        "change_type": change_type,
        "summary": str(lu["summary"]).strip(),
        "detail": detail,
        "rationale": str(lu.get("rationale") or "").strip(),
        "confidence": confidence if confidence in CONFIDENCE_LEVELS else "中",
    }


def build_proposal(chain_id: str, result: dict, *, items: list[dict],
                   date: str) -> dict | None:
    """parse + 补身份/证据字段，返回可落 pending 的完整提案；不合格返回 None。"""
    p = parse_logic_update(result)
    if p is None:
        return None
    target_key = _target_key(p["change_type"], p["detail"])
    if not target_key:
        return None
    p["chain_id"] = chain_id
    p["target_key"] = target_key
    p["proposal_id"] = f"{chain_id}:{p['change_type']}:{target_key}"
    p["proposed_at"] = date  # 回放时对齐信息日期而非当天（对齐发现引擎语义）
    p["source_info_ids"] = [it["info_id"] for it in items if it.get("info_id")]
    p["evidence"] = [{"date": date, "info_id": it["info_id"],
                      "title": it.get("title"), "source": it.get("source")}
                     for it in items if it.get("info_id")]
    return p


# ---------------------------------------------------------------- pending 持久化

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


def _merge_evidence(entry: dict, proposal: dict, *, date: str) -> None:
    """命中已有提案：合并证据与来源（按 info_id 去重），刷新 last_evidence_at。"""
    ev = entry.setdefault("evidence", [])
    have = {e.get("info_id") for e in ev if isinstance(e, dict)}
    for e in proposal.get("evidence") or []:
        if isinstance(e, dict) and e.get("info_id") not in have:
            ev.append(e)
            have.add(e.get("info_id"))
    if len(ev) > _MAX_EVIDENCE:
        del ev[:-_MAX_EVIDENCE]  # 只留最近 N 条，防无限膨胀
    ids = entry.setdefault("source_info_ids", [])
    known = set(ids)
    for i in proposal.get("source_info_ids") or []:
        if i not in known:
            ids.append(i)
            known.add(i)
    entry["last_evidence_at"] = date


def upsert_pending(new_proposals: list[dict], *, path: Path | str | None = None,
                   now: datetime | None = None) -> list[dict]:
    """按 proposal_id 去重追加；命中已有只合并证据；返回实际新增的提案。"""
    pending = load_pending(path)
    by_id = {p.get("proposal_id"): p for p in pending}
    today = (now or datetime.now()).date().isoformat()
    added: list[dict] = []
    for p in new_proposals:
        pid = p.get("proposal_id")
        if pid in by_id:
            _merge_evidence(by_id[pid], p, date=p.get("proposed_at") or today)
            continue
        entry = dict(p)
        entry.setdefault("proposed_at", today)
        entry["last_evidence_at"] = entry.get("proposed_at") or today
        pending.append(entry)
        by_id[pid] = entry
        added.append(entry)
    if new_proposals:
        save_pending(pending, path)
    return added


def append_evolution_audit(tracking_dir: Path | str, date: str,
                           proposals: list[dict], *, tick_label: str
                           ) -> Path | None:
    """演化提案日产出审计：evolution_<date>.json；空则静默。"""
    from investment_engine.chain_tracker.proposals import append_daily_audit

    return append_daily_audit(tracking_dir, date, proposals,
                              tick_label=tick_label, prefix="evolution")


# ---------------------------------------------------------------- 应用（confirm）

def _apply_add_node(chain: dict, detail: dict, change: dict) -> None:
    metric = detail.get("metric")
    if isinstance(metric, dict) and _as_nonempty_str(metric.get("metric")):
        metrics = chain.setdefault("tracking_metrics", [])
        if not any(m.get("metric") == metric["metric"] for m in metrics
                   if isinstance(m, dict)):
            metrics.append({k: metric.get(k) for k in (
                "metric", "current", "signal_direction", "source")
                if metric.get(k) is not None})
            change["applied"].append(f"新增跟踪指标 {metric['metric']}")
        else:
            change["skipped"].append(f"跟踪指标已存在 {metric['metric']}")
    stock = detail.get("stock")
    if isinstance(stock, dict) and _as_nonempty_str(stock.get("name")):
        code = str(stock.get("code") or "").strip()
        segment_ids = {s.get("id") for s in chain.get("segments") or []
                       if isinstance(s, dict)}
        if not _CODE_RE.match(code):
            change["skipped"].append(f"标的代码非法（跳过）: {stock.get('name')}")
        elif stock.get("segment") not in segment_ids:
            change["skipped"].append(
                f"标的 segment 未知（跳过）: {stock.get('name')}")
        else:
            mappings = chain.setdefault("mappings", [])
            if not any(str(m.get("code")) == code for m in mappings
                       if isinstance(m, dict)):
                mappings.append({
                    "code": code, "name": str(stock["name"]).strip(),
                    "segment": stock["segment"],
                    "relation": str(stock.get("relation") or "标的"),
                    "elasticity": "concept",  # 提案未经验证，保守标 concept
                })
                change["applied"].append(f"新增标的 {stock['name']}({code})")
            else:
                change["skipped"].append(f"标的已存在 {code}")


def _apply_refine_segment(chain: dict, detail: dict, change: dict) -> None:
    seg_id = str(detail["segment_id"]).strip()
    add = [str(m).strip() for m in detail.get("add_materials") or []
           if _as_nonempty_str(str(m))]
    segments = chain.setdefault("segments", [])
    seg = next((s for s in segments
                if isinstance(s, dict) and s.get("id") == seg_id), None)
    if seg is None:
        name = _as_nonempty_str(detail.get("segment_name"))
        if not name:
            change["skipped"].append(f"环节 {seg_id} 不存在且无 segment_name")
            return
        segments.append({"id": seg_id, "name": name, "materials": add})
        change["applied"].append(f"新增环节 {name}（{seg_id}）")
        return
    materials = seg.setdefault("materials", [])
    new = [m for m in add if m not in materials]
    materials.extend(new)
    change["applied"].append(f"环节 {seg_id} 新增材料 {len(new)} 项")


def _apply_focus_shift(chain: dict, detail: dict, change: dict) -> None:
    timing = chain.get("timing")
    if not isinstance(timing, dict):
        timing = {}
        chain["timing"] = timing
    for src, dst in (("recommendation", "current_recommendation"),
                     ("next_trigger", "next_trigger"), ("risk", "risk")):
        v = _as_nonempty_str(detail.get(src))
        if v:
            timing[dst] = v
    frm = detail.get("from_segment") or "?"
    note = f"重心 {frm}→{detail['to_segment']}"
    evidence = chain.get("stage_evidence") or ""
    chain["stage_evidence"] = f"{evidence}（演化确认：{note}）" if evidence else note
    change["applied"].append(note)


def _apply_update_thesis(chain: dict, detail: dict, change: dict) -> None:
    chain["thesis"] = str(detail["new_thesis"]).strip()
    change["applied"].append("thesis 已替换")


def _apply_update_falsification(chain: dict, detail: dict, change: dict) -> None:
    fals = chain.setdefault("falsification", [])
    for item in detail.get("add") or []:
        text = _as_nonempty_str(str(item))
        if text and text not in fals:
            fals.append(text)
            change["applied"].append(f"新增证伪条件: {text}")
    remove = {str(x).strip() for x in detail.get("remove") or []}
    if remove:
        before = len(fals)
        chain["falsification"] = [f for f in fals if f not in remove]
        n = before - len(chain["falsification"])
        if n:
            change["applied"].append(f"移除证伪条件 {n} 条")


def _apply_add_relation(chain: dict, detail: dict, change: dict) -> None:
    relations = chain.setdefault("chain_relations", [])
    target = str(detail["target"]).strip()
    relation = str(detail["relation"]).strip()
    if any(isinstance(r, dict) and r.get("target") == target
           and r.get("relation") == relation for r in relations):
        change["skipped"].append(f"跨链关系已存在 {target}/{relation}")
        return
    entry = {"target": target, "relation": relation}
    if _as_nonempty_str(detail.get("note")):
        entry["note"] = str(detail["note"]).strip()
    relations.append(entry)
    change["applied"].append(f"新增跨链关系 → {target}")


_APPLIERS = {
    "add_node": _apply_add_node,
    "refine_segment": _apply_refine_segment,
    "focus_shift": _apply_focus_shift,
    "update_thesis": _apply_update_thesis,
    "update_falsification": _apply_update_falsification,
    "add_relation": _apply_add_relation,
}


def apply_evolution(chain: dict, proposal: dict, *, today: str) -> dict:
    """把演化提案就地合并进 chain dict（增量合并，非整体替换）；返回变更摘要。

    幂等去重：tracking_metrics 按 metric、mappings 按 code、falsification 按文本、
    chain_relations 按 (target, relation)。调用方负责 store.save_chain 落盘
    （schema 强校验兜底）。
    """
    change: dict = {"chain_id": chain.get("chain_id"),
                    "change_type": proposal.get("change_type"),
                    "summary": proposal.get("summary"),
                    "applied": [], "skipped": []}
    applier = _APPLIERS.get(proposal.get("change_type"))
    if applier is None:
        change["skipped"].append(f"未知 change_type: {proposal.get('change_type')}")
        return change
    applier(chain, proposal.get("detail") or {}, change)

    history = chain.setdefault("history", [])
    history.append({
        "date": today,
        "stage": chain.get("current_stage") or "阶段0-观察",
        "action": f"演化:{proposal.get('change_type')} {proposal.get('summary')}",
        "result": "待验证",
    })
    return change


# ---------------------------------------------------------------- confirm / reject

def _find(pending: list[dict], proposal_id: str) -> dict | None:
    return next((p for p in pending if p.get("proposal_id") == proposal_id),
                None)


def confirm_evolution(proposal_id: str, *, pending_path: Path | str | None = None,
                      base_dir: Path | None = None,
                      today: str | None = None) -> Path:
    """人工确认：提案应用到 chain.yaml（schema 强校验，非法抛错不写入）并移出 pending。"""
    from investment_engine.industry_chain import store

    pending = load_pending(pending_path)
    entry = _find(pending, proposal_id)
    if entry is None:
        raise ValueError(f"待确认演化提案中不存在: {proposal_id!r}")
    chain_id = entry.get("chain_id")
    if chain_id not in store.list_chains(base_dir=base_dir):
        raise ValueError(f"产业链不存在（无 chain.yaml）: {chain_id!r}")

    today = today or datetime.now().date().isoformat()
    chain = store.load_chain(chain_id, base_dir=base_dir)
    apply_evolution(chain, entry, today=today)
    path = store.save_chain(chain, base_dir=base_dir)  # schema 强校验兜底
    save_pending([p for p in pending if p.get("proposal_id") != proposal_id],
                 pending_path)
    return path


def reject_evolution(proposal_id: str, *,
                     pending_path: Path | str | None = None) -> dict:
    """人工否决：从 pending 移除并返回被移除的提案。"""
    pending = load_pending(pending_path)
    entry = _find(pending, proposal_id)
    if entry is None:
        raise ValueError(f"待确认演化提案中不存在: {proposal_id!r}")
    save_pending([p for p in pending if p.get("proposal_id") != proposal_id],
                 pending_path)
    return entry
