"""发现引擎编排（T16）：每 30 分钟一个发现 tick。

流程（docs/tasks/m0-chain-industry-tracking.md Phase 3）：
  1. 拉取增量信息（研报 + 公告；不拉期货——品种全部预分配已有链，见计划文档决策 3）
  2. 去重过滤：discovery_items.db 48h 窗口（独立于跟踪 DB——跟踪会把未匹配项
     落账，共用 DB 会抑制发现候选）
  3. 触发过滤：标题含 涨价/扩产/缺货/供需/产业链/深度/专题
  4. 排除已有链增量：matching 匹配到已有 chain.yaml 的信息不是新产业链
  5. 候选分批 LLM 发现判断 → 提议去重 → 落 pending + 日产出审计
  6. TTL 清理内置在 tick 末尾

三条硬规则与跟踪引擎一致：去重键用 info_id；空批次静默（不调 LLM、不写提议）；
LLM 失败不落账（下一 tick 自愈重试）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from investment_engine.chain_tracker.analysis import default_llm_call
from investment_engine.chain_tracker.core import collect_items, load_chains
from investment_engine.chain_tracker.dedup import ProcessedItemsDB
from investment_engine.chain_tracker.discovery import (
    build_discovery_messages, build_momentum_messages, build_pending_index,
    filter_duplicate_proposals, is_discovery_candidate, parse_discovery,
)
from investment_engine.chain_tracker.futures import DEFAULT_THRESHOLD_PCT
from investment_engine.chain_tracker.matching import build_chain_index, match_items
from investment_engine.chain_tracker.momentum import (
    aggregate_theme_cards, judge_stage, trigger_themes,
)
from investment_engine.chain_tracker.proposals import (
    append_daily_audit, attach_evidence, load_pending, upsert_pending,
)
from investment_engine.chain_tracker.report import (
    append_tick_log, default_tracking_dir,
)
from investment_engine.chain_tracker.sector import (
    DEFAULT_SECTOR_THRESHOLD_PCT, load_sector_anomalies,
)


def default_discovery_db_path() -> Path:
    return default_tracking_dir() / "discovery_items.db"


def _record_rows(items: list[dict], **extra) -> list[dict]:
    return [{"info_id": i["info_id"], "source": i["source"], "title": i["title"],
             "published_at": i["published_at"], **extra} for i in items]


def run_discovery(*, date: str | None = None, now: datetime | None = None,
                  offline: bool = False, no_llm: bool = False,
                  dry_run: bool = False, source: str = "all",
                  base_dir: Path | None = None, tracking_dir: Path | None = None,
                  db_path: Path | None = None, research_root: Path | None = None,
                  sector_root: Path | None = None,
                  pool_root: Path | None = None,
                  sector_threshold_pct: float = DEFAULT_SECTOR_THRESHOLD_PCT,
                  session=None, call_fn=None, max_items_per_batch: int = 40,
                  warn=print) -> dict:
    """跑一个发现 tick；返回摘要 dict（含 proposals 列表）。

    source：all（默认）/ report（引擎 A 研报驱动）/ momentum（引擎 B 异动驱动）。
    """
    now = now or datetime.now()
    date = date or now.date().isoformat()
    window = f"{now.hour:02d}:{now.minute // 30 * 30:02d}"
    tracking_dir = Path(tracking_dir) if tracking_dir else default_tracking_dir()
    pending_path = tracking_dir / "proposals_pending.json"

    items = collect_items(
        date, offline=offline, research_root=research_root, session=session,
        now=now, fetch_futures_text=None, futures_state_path=None,
        futures_threshold_pct=DEFAULT_THRESHOLD_PCT, window=window, warn=warn,
        include_futures=False)

    # 板块异动触发源（任务书 §3.3：涨幅>3% 且无产业链归属）；本地 fund_flow 落盘
    try:
        sector_items = load_sector_anomalies(
            date, root=sector_root, threshold_pct=sector_threshold_pct)
    except Exception as e:  # noqa: BLE001 - 触发源缺席不阻断 tick
        warn(f"板块异动读取失败: {e}")
        sector_items = []
    items.extend(sector_items)

    # 引擎 B 信号聚合（规则层，零 LLM；设计文档 §4.1-4.2）
    mom_cards: list[dict] = []
    if source in ("all", "momentum"):
        try:
            mom_cards = trigger_themes(aggregate_theme_cards(
                date, pool_root=pool_root, flow_root=sector_root))
        except Exception as e:  # noqa: BLE001 - 数据源缺席不阻断 tick
            warn(f"异动聚合失败: {e}")
            mom_cards = []

    summary: dict = {"date": date, "tick": window, "fetched": len(items),
                     "new_items": 0, "sector_anomalies": len(sector_items),
                     "momentum_triggers": len(mom_cards),
                     "evidence_hits": 0, "evidence": {},
                     "candidates": 0, "llm_calls": 0,
                     "llm_errors": 0, "proposals": [], "skipped_duplicates": [],
                     "added": [], "db_cleaned": 0}

    with ProcessedItemsDB(db_path or default_discovery_db_path()) as db:
        if not dry_run:
            fresh_ids = set(db.filter_unprocessed(
                [i["info_id"] for i in items], now=now))
        else:  # dry_run 不写 DB，把所有信息当新信息预览
            fresh_ids = {i["info_id"] for i in items}
        new_items = [i for i in items if i["info_id"] in fresh_ids]
        summary["new_items"] = len(new_items)

        pending = load_pending(pending_path)

        # 证据累积：命中待确认提议的信息挂为证据，不再进入发现候选
        # （候选池语义：提议躺着累积证据，证据够了人工 confirm 进观察列表）
        if pending and new_items:
            ev_matches: dict[str, list[dict]] = {}
            for item, cid in match_items(new_items, build_pending_index(pending)):
                ev_matches.setdefault(cid, []).append(item)
            ev_ids = {i["info_id"] for its in ev_matches.values() for i in its}
            summary["evidence_hits"] = len(ev_ids)
            summary["evidence"] = {cid: len(its)
                                   for cid, its in ev_matches.items()}
            if ev_matches and not dry_run:
                attach_evidence(ev_matches, path=pending_path, date=date)
                db.record_many(
                    [{"info_id": i["info_id"], "source": i["source"],
                      "title": i["title"], "published_at": i["published_at"],
                      "chain_id": cid, "llm_verdict": "evidence"}
                     for cid, its in ev_matches.items() for i in its], now=now)
            new_items = [i for i in new_items if i["info_id"] not in ev_ids]

        # 板块异动裸行改道（引擎 B 设计 §4.5）：不进研报 prompt（实证 100%
        # no_proposal）；有归属记 matched_existing，无归属记 sector_routed
        # 落账防复扫，由异动分支基于涨停池聚合成热度卡后自评估
        sector_rows = [i for i in new_items if i.get("source") == "sector"]
        new_items = [i for i in new_items if i.get("source") != "sector"]

        # 触发过滤：无触发词的直接落账（确定性过滤，永不成为候选）
        triggered = [i for i in new_items if is_discovery_candidate(i)]
        if not dry_run:
            db.record_many(_record_rows(
                [i for i in new_items if not is_discovery_candidate(i)]), now=now)

        chains: dict = {}
        chain_index: dict = {}
        if triggered or sector_rows or mom_cards:
            chains = load_chains(base_dir, warn)
            chain_index = build_chain_index(list(chains.values()))

        if sector_rows:
            sector_matched: dict[str, str] = {}
            for item, cid in match_items(sector_rows, chain_index):
                sector_matched.setdefault(item["info_id"], cid)
            if not dry_run:
                db.record_many(
                    [{"info_id": i["info_id"], "source": i["source"],
                      "title": i["title"], "published_at": i["published_at"],
                      "chain_id": sector_matched.get(i["info_id"]),
                      "llm_verdict": ("matched_existing"
                                      if i["info_id"] in sector_matched
                                      else "sector_routed")}
                     for i in sector_rows], now=now)

        if triggered and source in ("all", "report"):
            pairs = match_items(triggered, chain_index)
            matched: dict[str, str] = {}
            for item, cid in pairs:
                matched.setdefault(item["info_id"], cid)
            # 已有链的增量信息不是新产业链（落账 matched_existing 防复扫）
            candidates = [i for i in triggered if i["info_id"] not in matched]
            summary["candidates"] = len(candidates)
            if not dry_run:
                db.record_many(
                    [{"info_id": i["info_id"], "source": i["source"],
                      "title": i["title"], "published_at": i["published_at"],
                      "chain_id": matched[i["info_id"]],
                      "llm_verdict": "matched_existing"}
                     for i in triggered if i["info_id"] in matched], now=now)

            if candidates and not no_llm:
                # no_llm 模式：候选不落账，留给真实跑（同跟踪引擎语义）
                call = call_fn or partial(default_llm_call, tag="chain_discovery")
                found: list[dict] = []
                for i in range(0, len(candidates), max_items_per_batch):
                    batch = candidates[i:i + max_items_per_batch]
                    summary["llm_calls"] += 1
                    try:
                        props = parse_discovery(call(
                            build_discovery_messages(
                                list(chains.values()), pending, batch,
                                max_items=max_items_per_batch)))
                    except Exception as e:  # noqa: BLE001 - 单批失败不阻断其他批
                        summary["llm_errors"] += 1
                        warn(f"LLM 发现判断失败（本批 {len(batch)} 条不落账，"
                             f"下一 tick 自愈重试）: {e}")
                        continue
                    for p in props:
                        if not p["source_info_ids"]:
                            p["source_info_ids"] = [b["info_id"] for b in batch]
                    found.extend(props)
                    # 逐批即时落账：进程被杀不丢已完成批次的进度
                    if not dry_run:
                        db.record_many(_record_rows(
                            batch,
                            llm_verdict="proposed" if props else "no_proposal",
                            analysis=json.dumps(
                                {"proposals": [p["chain_id"] for p in props]},
                                ensure_ascii=False)), now=now)

                kept, skipped = filter_duplicate_proposals(
                    found, list(chains.values()), pending)
                summary["skipped_duplicates"] = [p["chain_id"] for p in skipped]
                for p in kept:
                    p["proposed_at"] = date  # 回放时对齐信息日期而非当天
                summary["proposals"] = kept
                if kept and not dry_run:
                    added = upsert_pending(kept, path=pending_path, now=now)
                    summary["added"] = [p["chain_id"] for p in added]
                    append_daily_audit(tracking_dir, date, added,
                                       tick_label=window)

        # ---- 引擎 B：异动驱动（设计文档 §4.5）----
        if mom_cards and source in ("all", "momentum"):
            mid_of = {c["theme"]: f"sector:{date}:momentum:{c['theme']}"
                      for c in mom_cards}
            if dry_run:
                fresh_cards = mom_cards
            else:
                fresh_mids = set(db.filter_unprocessed(
                    list(mid_of.values()), now=now))
                fresh_cards = [c for c in mom_cards
                               if mid_of[c["theme"]] in fresh_mids]
            if fresh_cards:
                pseudo = {
                    c["theme"]: {
                        "info_id": mid_of[c["theme"]], "source": "sector",
                        "title": (f"{c['theme']}板块异动：涨停{c['zt_count']}家，"
                                  f"领涨{'、'.join(c.get('leaders') or [])}"),
                        "published_at": date, "stock_code": None,
                        "stock_name": None, "chain_ids": []}
                    for c in fresh_cards}
                pseudo_items = list(pseudo.values())

                # 已有链 → matched_existing；pending → 证据累积；幸存 → LLM 拆链
                mom_matched: dict[str, str] = {}
                for item, cid in match_items(pseudo_items, chain_index):
                    mom_matched.setdefault(item["info_id"], cid)
                mom_pending: dict[str, str] = {}
                for item, cid in match_items(
                        [i for i in pseudo_items
                         if i["info_id"] not in mom_matched],
                        build_pending_index(pending)):
                    mom_pending.setdefault(item["info_id"], cid)

                if mom_pending and not dry_run:
                    ev_m: dict[str, list[dict]] = {}
                    for item in pseudo_items:
                        cid = mom_pending.get(item["info_id"])
                        if cid:
                            ev_m.setdefault(cid, []).append(item)
                    if ev_m:
                        attach_evidence(ev_m, path=pending_path, date=date)
                        summary["evidence_hits"] += sum(
                            len(v) for v in ev_m.values())
                        for cid, its in ev_m.items():
                            summary["evidence"][cid] = (
                                summary["evidence"].get(cid, 0) + len(its))
                if not dry_run:
                    db.record_many(
                        [{"info_id": i["info_id"], "source": i["source"],
                          "title": i["title"], "published_at": i["published_at"],
                          "chain_id": mom_matched[i["info_id"]],
                          "llm_verdict": "matched_existing"}
                         for i in pseudo_items if i["info_id"] in mom_matched]
                        + [{"info_id": i["info_id"], "source": i["source"],
                            "title": i["title"],
                            "published_at": i["published_at"],
                            "chain_id": mom_pending[i["info_id"]],
                            "llm_verdict": "evidence"}
                           for i in pseudo_items if i["info_id"] in mom_pending],
                        now=now)

                survivors = [c for c in fresh_cards
                             if mid_of[c["theme"]] not in mom_matched
                             and mid_of[c["theme"]] not in mom_pending]
                if survivors and not no_llm:
                    summary["proposals"].extend(_momentum_llm_proposals(
                        survivors, mid_of, chains, pending, new_items,
                        date=date, now=now, db=db, dry_run=dry_run,
                        pool_root=pool_root, sector_root=sector_root,
                        pending_path=pending_path,
                        call_fn=call_fn, summary=summary, warn=warn))

        if not dry_run:
            summary["db_cleaned"] = db.cleanup(now=now)

    if not dry_run:
        append_tick_log(tracking_dir / "discovery_ticks.jsonl", {
            "date": date, "tick": window, "fetched": summary["fetched"],
            "new_items": summary["new_items"],
            "sector_anomalies": summary["sector_anomalies"],
            "momentum_triggers": summary["momentum_triggers"],
            "evidence_hits": summary["evidence_hits"],
            "candidates": summary["candidates"],
            "llm_calls": summary["llm_calls"],
            "llm_errors": summary["llm_errors"],
            "proposals": [p["chain_id"] for p in summary["proposals"]],
            "skipped_duplicates": summary["skipped_duplicates"],
        })
    return summary


def _momentum_llm_proposals(cards: list[dict], mid_of: dict[str, str],
                            chains: dict, pending: list[dict],
                            items: list[dict], *,
                            date: str, now: datetime, db, dry_run: bool,
                            pool_root, sector_root, pending_path: Path,
                            call_fn, summary: dict, warn) -> list[dict]:
    """幸存异动题材逐题材调 LLM 拆链（设计文档 §4.4-4.5）。

    阶段由 momentum.judge_stage 规则初判并强制覆盖 LLM 输出；
    source_info_ids 由系统填充（不信 LLM）。LLM 失败的题材不落账，
    下一 tick 自愈重试（与研报路径同纪律）。
    """
    call = call_fn or partial(default_llm_call, tag="chain_discovery")
    prev_date = (datetime.strptime(date, "%Y-%m-%d")
                 - timedelta(days=1)).date().isoformat()
    try:
        prev_cards = {c["theme"]: c for c in aggregate_theme_cards(
            prev_date, pool_root=pool_root, flow_root=sector_root)}
    except Exception:  # noqa: BLE001 - 前日数据缺席只影响阶段细分
        prev_cards = {}

    def _related(card: dict) -> list[dict]:
        theme = card["theme"]
        leaders = [n for n in (card.get("leaders") or []) if n]
        out = [i for i in items
               if theme in (i.get("title") or "")
               or any(n in (i.get("title") or "") for n in leaders)]
        return out[:10]

    found: list[dict] = []
    for card in cards:
        mid = mid_of[card["theme"]]
        stage, ev = judge_stage(card, prev_card=prev_cards.get(card["theme"]))
        related = _related(card)
        summary["llm_calls"] += 1
        try:
            props = parse_discovery(call(build_momentum_messages(
                card, list(chains.values()), pending, related, stage=stage)))
        except Exception as e:  # noqa: BLE001 - 单题材失败不阻断其他题材
            summary["llm_errors"] += 1
            warn(f"LLM 异动拆链失败（{card['theme']} 不落账，"
                 f"下一 tick 自愈重试）: {e}")
            continue
        for p in props:
            p["source_type"] = "momentum"
            p["current_stage"] = stage
            p["stage_evidence"] = ev
            p["source_info_ids"] = [mid] + [i["info_id"] for i in related]
        found.extend(props)
        if not dry_run:
            db.record_many([{
                "info_id": mid, "source": "sector",
                "title": f"{card['theme']}板块异动", "published_at": date,
                "chain_id": None,
                "llm_verdict": "proposed" if props else "no_proposal",
                "analysis": json.dumps(
                    {"stage": stage, "proposals": [p["chain_id"] for p in props]},
                    ensure_ascii=False)}], now=now)

    if not found:
        return []
    kept, skipped = filter_duplicate_proposals(
        found, list(chains.values()), pending)
    summary["skipped_duplicates"].extend(p["chain_id"] for p in skipped)
    for p in kept:
        p["proposed_at"] = date
    if kept and not dry_run:
        added = upsert_pending(kept, path=pending_path, now=now)
        summary["added"].extend(p["chain_id"] for p in added)
        append_daily_audit(Path(pending_path).parent, date, added,
                           tick_label=summary["tick"])
    return kept
