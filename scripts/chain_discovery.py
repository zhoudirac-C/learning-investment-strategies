#!/usr/bin/env python3
"""产业链发现引擎（M0-Chain Phase 3 引擎 A）——30 分钟 tick 入口。

用法：
    python scripts/chain_discovery.py                  # 发现 tick（拉取当日研报/公告）
    python scripts/chain_discovery.py --offline        # 只用本地 infra/data/research 文件
    python scripts/chain_discovery.py --date 2026-08-28 --offline   # 回放某天
    python scripts/chain_discovery.py --no-llm         # 只做触发+匹配过滤（调试候选用）
    python scripts/chain_discovery.py --dry-run        # 预览：不写 DB/pending/审计

    python scripts/chain_discovery.py list             # 列出待确认提议
    python scripts/chain_discovery.py confirm <chain_id>   # 确认 → 创建 chain.yaml
    python scripts/chain_discovery.py reject <chain_id>    # 否决 → 移出 pending

cron 注意：LLM 优先走 Hermes 全局模型配置（resolve_runtime_provider，跟随
~/.hermes/config.yaml 的 model.default，不写死）；全局不可用时回落 .env 通道
（SENSENOVA_API_KEY / DEEPSEEK_API_KEY → ZHIPU_API_KEY 的 GLM）。本脚本自身不读
.env——经 ~/.hermes/scripts/qing_chain_discovery.py 包装脚本调度（自动注入 .env）。

产物：
    infra/data/chain_tracking/discovery_items.db        发现侧去重 DB（48h TTL，
                                                        独立于跟踪 processed_items.db）
    infra/data/chain_tracking/proposals_pending.json    待人工确认提议（正本）
    infra/data/chain_tracking/proposals_<date>.json     日产出审计
    infra/data/chain_tracking/discovery_ticks.jsonl     每 tick 机器可读摘要

人工确认流程：提议自动落 proposals_pending.json（候选池，每个 tick 持续命中
新信息累积证据）→ 人工 review → confirm 创建
knowledge/industry-chains/<chain_id>/chain.yaml（schema 强校验，阶段0-观察起步），
跟踪引擎（scripts/chain_tracker.py）下一 tick 起自动纳入该链。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _cmd_scan(args: argparse.Namespace) -> int:
    from investment_engine.chain_tracker.discovery_core import run_discovery

    summary = run_discovery(date=args.date, offline=args.offline,
                            no_llm=args.no_llm, dry_run=args.dry_run)

    mode = ("dry-run" if args.dry_run else "no-llm" if args.no_llm
            else "offline" if args.offline else "live")
    print(f"[chain_discovery] {summary['date']} {summary['tick']} ({mode}) "
          f"fetched={summary['fetched']} new={summary['new_items']} "
          f"sector={summary['sector_anomalies']} "
          f"evidence={summary['evidence_hits']} "
          f"candidates={summary['candidates']} llm={summary['llm_calls']} "
          f"errors={summary['llm_errors']} "
          f"proposals={len(summary['proposals'])}")
    for cid, n in summary["evidence"].items():
        print(f"  📎 证据累积 +{n} 条 → {cid}（待确认提议）")
    for p in summary["proposals"]:
        print(f"  💡 {p['name']}（{p['chain_id']}，{p['current_stage']}，"
              f"置信度 {p['confidence']}）")
        print(f"     驱动：{p['driver']}")
        print(f"     时机：{p.get('timing') or '-'}")
    if summary["skipped_duplicates"]:
        print(f"  跳过重复提议: {', '.join(summary['skipped_duplicates'])}")
    if summary["added"]:
        print("  已写入 proposals_pending.json，"
              "请 review 后 `confirm <chain_id>` 确认")
    return 1 if summary["llm_errors"] else 0


def _cmd_list(_args: argparse.Namespace) -> int:
    from investment_engine.chain_tracker.proposals import load_pending

    pending = load_pending()
    if not pending:
        print("[chain_discovery] 无待确认提议")
        return 0
    print(f"[chain_discovery] 待确认提议 {len(pending)} 条（候选池，证据会持续累积）：")
    for p in pending:
        ev = p.get("evidence") or []
        print(f"  - {p['chain_id']} | {p['name']} | 提议 {p.get('current_stage')}"
              f"（置信度 {p.get('confidence')}，提议于 {p.get('proposed_at')}）")
        print(f"    驱动：{p.get('driver')}")
        print(f"    来源：{p.get('source')} 信息 {len(p.get('source_info_ids') or [])} 条")
        print(f"    证据累积：{len(ev)} 条"
              f"（最近 {p.get('last_evidence_at') or '-'}）")
        if len(ev) >= 3:
            print("    → 证据已积累 ≥3 条，可考虑 confirm 加入观察列表")
    print("\n确认（加入观察列表，阶段0起步）: "
          "python scripts/chain_discovery.py confirm <chain_id>")
    print("否决: python scripts/chain_discovery.py reject <chain_id>")
    return 0


def _cmd_confirm(args: argparse.Namespace) -> int:
    from investment_engine.chain_tracker.proposals import confirm_proposal

    try:
        path = confirm_proposal(args.chain_id)
    except ValueError as e:
        print(f"[chain_discovery] 确认失败: {e}", file=sys.stderr)
        return 1
    print(f"[chain_discovery] 已创建 {path}")
    print("  已加入观察列表（阶段0-观察起步，阶段推进交给跟踪引擎）；")
    print("  跟踪引擎下一 tick 起自动纳入该链；tracking_metrics/falsification "
          "为提议初稿，请人工补全。")
    return 0


def _cmd_reject(args: argparse.Namespace) -> int:
    from investment_engine.chain_tracker.proposals import reject_proposal

    try:
        removed = reject_proposal(args.chain_id)
    except ValueError as e:
        print(f"[chain_discovery] 否决失败: {e}", file=sys.stderr)
        return 1
    print(f"[chain_discovery] 已否决并移出 pending: "
          f"{removed['chain_id']}（{removed.get('name')}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="产业链发现引擎 30 分钟 tick")
    p.add_argument("--date", help="YYYY-MM-DD，默认今天")
    p.add_argument("--offline", action="store_true",
                   help="只用本地 research 文件，不拉取")
    p.add_argument("--no-llm", action="store_true",
                   help="只做去重+触发/匹配过滤，不调 LLM（候选不落账，留给真实跑）")
    p.add_argument("--dry-run", action="store_true",
                   help="预览：不写 DB/pending/审计")
    args, rest = p.parse_known_args(argv)

    if rest and rest[0] in ("list", "confirm", "reject"):
        sub = argparse.ArgumentParser(prog=f"chain_discovery.py {rest[0]}")
        if rest[0] in ("confirm", "reject"):
            sub.add_argument("chain_id")
        sub_args = sub.parse_args(rest[1:])
        return {"list": _cmd_list, "confirm": _cmd_confirm,
                "reject": _cmd_reject}[rest[0]](sub_args)
    if rest:
        p.error(f"未知参数/子命令: {' '.join(rest)}")
    return _cmd_scan(args)


if __name__ == "__main__":
    sys.exit(main())
