"""每 30 分钟 tick 编排（T9）。

流程（docs/tasks/m0-chain-industry-tracking.md Phase 2）：
  1. 拉取增量信息（研报 + 公告 + 期货行情）
  2. 去重过滤：processed_items DB 48h 窗口内处理过的跳过
  3. 新信息匹配产业链 → 按链分批 LLM 分析（UP 5 步推理框架）
  4. 有状态变化的链 → 更新 chain.yaml + 追加 history
  5. 有变化的链 → 输出增量报告（无变化静默）
  6. TTL 清理内置在 tick 末尾

三条硬规则：去重键用 info_id；空批次静默（不调 LLM、不写报告）；TTL 顺手清理。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from investment_engine.chain_tracker.analysis import analyze_chain
from investment_engine.chain_tracker.dedup import ProcessedItemsDB, default_db_path
from investment_engine.chain_tracker.evolution import (
    append_evolution_audit, build_proposal, upsert_pending,
)
from investment_engine.chain_tracker.futures import (
    DEFAULT_THRESHOLD_PCT, detect_anomalies, fetch_quotes,
)
from investment_engine.chain_tracker.items import normalize_notice, normalize_report
from investment_engine.chain_tracker.matching import build_chain_index, match_items
from investment_engine.chain_tracker.report import (
    append_daily_report, append_tick_log, default_tracking_dir,
)
from investment_engine.chain_tracker.state import apply_chain_update


def _load_local_json(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def collect_items(date: str, *, offline: bool, research_root: Path | None,
                  session, now: datetime, fetch_futures_text,
                  futures_state_path: Path | None,
                  futures_threshold_pct: float, window: str,
                  warn, include_futures: bool = True) -> list[dict]:
    from investment_engine import research_feed

    root = research_root if research_root is not None else research_feed.DEFAULT_ROOT
    items: list[dict] = []

    reports = None
    if not offline:
        try:
            rows = research_feed.fetch_reports_range(date, date, session=session)
            reports = [r for r in rows
                       if str(r.get("publish_date") or "")[:10] == date]
        except Exception as e:  # noqa: BLE001 - 单源失败回退本地，不阻断 tick
            warn(f"研报拉取失败，回退本地文件: {e}")
    if reports is None:
        reports = _load_local_json(research_feed.reports_path(date, root))
    items.extend(normalize_report(r) for r in reports if r.get("info_code"))

    notices = None
    if not offline:
        try:
            notices = research_feed.fetch_notices(date)
        except Exception as e:  # noqa: BLE001
            warn(f"公告拉取失败，回退本地文件: {e}")
    if notices is None:
        notices = _load_local_json(research_feed.notices_path(date, root))
    items.extend(normalize_notice(n) for n in notices if n.get("title"))

    if not include_futures:
        return items
    try:
        quotes = fetch_quotes(fetch_text=fetch_futures_text)
    except Exception as e:  # noqa: BLE001 - 期货源失败不阻断 tick
        warn(f"期货行情拉取失败: {e}")
        quotes = {}
    items.extend(detect_anomalies(
        quotes, threshold_pct=futures_threshold_pct,
        state_path=futures_state_path, date=date, window=window))
    return items


def load_chains(base_dir: Path | None, warn) -> dict[str, dict]:
    from investment_engine.industry_chain import store

    chains: dict[str, dict] = {}
    for cid in store.list_chains(base_dir=base_dir):
        try:
            chains[cid] = store.load_chain(cid, base_dir=base_dir)
        except Exception as e:  # noqa: BLE001 - 单链损坏不阻断其他链
            warn(f"chain.yaml 加载失败（跳过 {cid}）: {e}")
    return chains


def run_tick(*, date: str | None = None, now: datetime | None = None,
             offline: bool = False, no_llm: bool = False, dry_run: bool = False,
             base_dir: Path | None = None, tracking_dir: Path | None = None,
             db_path: Path | None = None, research_root: Path | None = None,
             session=None, call_fn=None, fetch_futures_text=None,
             futures_threshold_pct: float = DEFAULT_THRESHOLD_PCT,
             max_items_per_chain: int = 30,
             warn=print) -> dict:
    """跑一个 tick；返回摘要 dict（含 changes 列表）。"""
    from investment_engine.industry_chain import store

    now = now or datetime.now()
    date = date or now.date().isoformat()
    window = f"{now.hour:02d}:{now.minute // 30 * 30:02d}"
    tracking_dir = Path(tracking_dir) if tracking_dir else default_tracking_dir()
    futures_state_path = None if dry_run else tracking_dir / "futures_state.json"

    items = collect_items(
        date, offline=offline, research_root=research_root, session=session,
        now=now, fetch_futures_text=fetch_futures_text,
        futures_state_path=futures_state_path,
        futures_threshold_pct=futures_threshold_pct, window=window, warn=warn)

    summary: dict = {"date": date, "tick": window, "fetched": len(items),
                     "new_items": 0, "matched_pairs": 0, "chains_analyzed": [],
                     "llm_calls": 0, "llm_errors": 0, "changes": [],
                     "evolution_proposals": [],
                     "processed_ids": [], "report_path": None, "db_cleaned": 0}

    with ProcessedItemsDB(db_path or default_db_path()) as db:
        if not dry_run:
            fresh_ids = set(db.filter_unprocessed(
                [i["info_id"] for i in items], now=now))
        else:  # dry_run 不写 DB，把所有信息当新信息预览
            fresh_ids = {i["info_id"] for i in items}
        new_items = [i for i in items if i["info_id"] in fresh_ids]
        summary["new_items"] = len(new_items)
        summary["processed_ids"] = [i["info_id"] for i in new_items]

        if new_items:
            chains = load_chains(base_dir, warn)
            pairs = match_items(new_items, build_chain_index(list(chains.values())))
            summary["matched_pairs"] = len(pairs)

            matched_ids = {i["info_id"] for i, _ in pairs}
            unmatched = [i for i in new_items if i["info_id"] not in matched_ids]
            if unmatched and not dry_run:
                db.record_many(
                    [{"info_id": i["info_id"], "source": i["source"],
                      "title": i["title"], "published_at": i["published_at"]}
                     for i in unmatched], now=now)

            by_chain: dict[str, list[dict]] = {}
            for item, cid in pairs:
                by_chain.setdefault(cid, []).append(item)

            for cid in sorted(by_chain):
                chain_items = by_chain[cid]
                if no_llm:
                    continue  # no_llm 模式：matched 项不落账，留给真实跑
                chain = chains.get(cid)
                if chain is None:
                    continue
                summary["llm_calls"] += 1
                summary["chains_analyzed"].append(cid)
                try:
                    result = analyze_chain(chain, chain_items, call_fn=call_fn,
                                           max_items=max_items_per_chain)
                except Exception as e:  # noqa: BLE001 - 单链失败不阻断其他链
                    summary["llm_errors"] += 1
                    warn(f"LLM 分析失败（{cid}）: {e}")
                    # 不落账：瞬时失败（限流/网络）留给下一 tick 自愈重试，
                    # 避免配额故障把整日信息烧成 "error" 记录（2026-08-31 实测教训）
                    continue

                # 逐链即时落账：进程中途被杀也不丢已完成的进度
                # （2026-08-31 全日回放被 timeout 杀死后 189 条已分析信息全部丢失的教训）
                if not dry_run:
                    db.record_many(
                        [{"info_id": it["info_id"], "source": it["source"],
                          "title": it["title"], "published_at": it["published_at"],
                          "chain_id": cid, "llm_verdict": result["verdict"],
                          "analysis": json.dumps(
                              {cid: {"verdict": result["verdict"],
                                     "summary": result.get("summary"),
                                     "stage_change": (result.get("step5_recommendation") or {})
                                     .get("stage_change")}},
                              ensure_ascii=False)}
                         for it in chain_items], now=now)

                change = apply_chain_update(chain, result, today=date)
                if change:
                    change["info_ids"] = [it["info_id"] for it in chain_items]
                    summary["changes"].append(change)
                    if not dry_run:
                        store.save_chain(chain, base_dir=base_dir)

                # 逻辑演化提案（Step 6）：结构性增量落 pending，人工 confirm 后
                # 才应用——不自动改 chain.yaml（区别于阶段更新的自动回写）。
                # 同 identity 再命中只合并证据，不重复占位（候选池语义）。
                proposal = build_proposal(cid, result, items=chain_items, date=date)
                if proposal is not None:
                    proposal["chain_name"] = chain.get("name")
                    summary["evolution_proposals"].append(proposal)
                    if not dry_run:
                        added = upsert_pending(
                            [proposal],
                            path=tracking_dir / "evolution_pending.json", now=now)
                        if added:
                            append_evolution_audit(tracking_dir, date, added,
                                                   tick_label=window)

        if not dry_run:
            summary["db_cleaned"] = db.cleanup(now=now)

    if not dry_run and (summary["changes"] or summary["evolution_proposals"]):
        out = append_daily_report(tracking_dir / f"daily_report_{date}.md",
                                  summary["changes"], tick_label=window,
                                  evolution=summary["evolution_proposals"])
        summary["report_path"] = str(out) if out else None

    if not dry_run:
        append_tick_log(tracking_dir / "ticks.jsonl", {
            "date": date, "tick": window, "fetched": summary["fetched"],
            "new_items": summary["new_items"],
            "matched_pairs": summary["matched_pairs"],
            "llm_calls": summary["llm_calls"],
            "llm_errors": summary["llm_errors"],
            "changed_chains": [c["chain_id"] for c in summary["changes"]],
            "evolution": [p["proposal_id"] for p in summary["evolution_proposals"]],
        })
    return summary
