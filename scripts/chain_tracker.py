#!/usr/bin/env python3
"""产业链跟踪引擎（M0-Chain Phase 2 引擎 B）——30 分钟 tick 入口。

用法：
    python scripts/chain_tracker.py                  # 正常 tick（拉取当日研报/公告/期货）
    python scripts/chain_tracker.py --offline        # 只用本地 infra/data/research 文件
    python scripts/chain_tracker.py --date 2026-08-28 --offline   # 回放某天
    python scripts/chain_tracker.py --no-llm         # 只做匹配不落 LLM 账（调试匹配用）
    python scripts/chain_tracker.py --dry-run        # 预览：不写 DB/chain.yaml/报告

    python scripts/chain_tracker.py evolution list               # 列出待确认演化提案
    python scripts/chain_tracker.py evolution confirm <proposal_id>  # 确认 → 应用到 chain.yaml
    python scripts/chain_tracker.py evolution reject <proposal_id>   # 否决 → 移出 pending

cron 注意：LLM 优先走 Hermes 全局模型配置（resolve_runtime_provider，跟随
~/.hermes/config.yaml 的 model.default，不写死）；全局不可用时回落 .env 通道
（SENSENOVA_API_KEY / DEEPSEEK_API_KEY → ZHIPU_API_KEY 的 GLM）。本脚本自身不读
.env——经 ~/.hermes/scripts/qing_chain_tracker.py 包装脚本调度（自动注入 .env）。

产物：
    infra/data/chain_tracking/processed_items.db     去重 DB（48h TTL）
    infra/data/chain_tracking/daily_report_<date>.md 增量日报（有变化的链 + 演化提案）
    infra/data/chain_tracking/ticks.jsonl            每 tick 机器可读摘要
    infra/data/chain_tracking/futures_state.json     期货告警防抖状态
    infra/data/chain_tracking/evolution_pending.json 待确认逻辑演化提案（正本）
    infra/data/chain_tracking/evolution_<date>.json  演化提案日产出审计

逻辑演化提案（2026-08-31，设计 docs/superpowers/specs/2026-08-31-chain-logic-evolution-design.md）：
LLM 在阶段判断（Step 5）之外顺带做演化判断（Step 6）：新信息若给产业链逻辑结构
本身带来增量（环节细化/新增节点/重心转移/thesis修正/证伪更新/跨链传导），落
evolution_pending.json；人工 review 后 confirm 应用到 chain.yaml（schema 强校验），
不自动改结构——区别于阶段更新的自动回写。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.chain_tracker.core import run_tick  # noqa: E402


def _cmd_scan(args: argparse.Namespace) -> int:
    summary = run_tick(date=args.date, offline=args.offline,
                       no_llm=args.no_llm, dry_run=args.dry_run)

    mode = ("dry-run" if args.dry_run else "no-llm" if args.no_llm
            else "offline" if args.offline else "live")
    print(f"[chain_tracker] {summary['date']} {summary['tick']} ({mode}) "
          f"fetched={summary['fetched']} new={summary['new_items']} "
          f"matched={summary['matched_pairs']} llm={summary['llm_calls']} "
          f"errors={summary['llm_errors']} changes={len(summary['changes'])} "
          f"evolution={len(summary['evolution_proposals'])}")
    for c in summary["changes"]:
        print(f"  ⚡ {c['chain_name']}: {c['old_stage']} → {c['new_stage']} "
              f"({c['verdict']}) {c['summary']}")
    for p in summary["evolution_proposals"]:
        print(f"  🧬 {p.get('chain_name') or p['chain_id']}（{p['chain_id']}）"
              f"[{p['change_type']}] {p['summary']}（置信度 {p['confidence']}）")
        print(f"     依据：{p.get('rationale') or '-'}")
    if summary["evolution_proposals"] and not args.dry_run:
        print("  演化提案已入 evolution_pending.json，review 后 "
              "`evolution confirm <proposal_id>` 应用")
    if summary["report_path"]:
        print(f"  报告: {summary['report_path']}")
    return 1 if summary["llm_errors"] else 0


def _cmd_evo_list(_args: argparse.Namespace) -> int:
    from investment_engine.chain_tracker.evolution import load_pending

    pending = load_pending()
    if not pending:
        print("[chain_tracker] 无待确认演化提案")
        return 0
    print(f"[chain_tracker] 待确认演化提案 {len(pending)} 条：")
    for p in pending:
        ev = p.get("evidence") or []
        print(f"  - {p['proposal_id']}")
        print(f"    [{p.get('change_type')}] {p.get('summary')}"
              f"（置信度 {p.get('confidence')}，提议于 {p.get('proposed_at')}）")
        print(f"    依据：{p.get('rationale') or '-'}")
        print(f"    证据累积：{len(ev)} 条（最近 {p.get('last_evidence_at') or '-'}）")
    print("\n确认（应用到 chain.yaml）: "
          "python scripts/chain_tracker.py evolution confirm <proposal_id>")
    print("否决: python scripts/chain_tracker.py evolution reject <proposal_id>")
    return 0


def _cmd_evo_confirm(args: argparse.Namespace) -> int:
    from investment_engine.chain_tracker.evolution import confirm_evolution

    try:
        path = confirm_evolution(args.proposal_id)
    except ValueError as e:
        print(f"[chain_tracker] 确认失败: {e}", file=sys.stderr)
        return 1
    print(f"[chain_tracker] 已应用演化提案并更新 {path}")
    return 0


def _cmd_evo_reject(args: argparse.Namespace) -> int:
    from investment_engine.chain_tracker.evolution import reject_evolution

    try:
        removed = reject_evolution(args.proposal_id)
    except ValueError as e:
        print(f"[chain_tracker] 否决失败: {e}", file=sys.stderr)
        return 1
    print(f"[chain_tracker] 已否决并移出 pending: "
          f"{removed['proposal_id']}（{removed.get('summary')}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="产业链跟踪引擎 30 分钟 tick")
    p.add_argument("--date", help="YYYY-MM-DD，默认今天")
    p.add_argument("--offline", action="store_true",
                   help="只用本地 research 文件，不拉取")
    p.add_argument("--no-llm", action="store_true",
                   help="只做去重+匹配，不调 LLM（matched 项不落账，留给真实跑）")
    p.add_argument("--dry-run", action="store_true",
                   help="预览：不写 DB/chain.yaml/报告/pending")
    args, rest = p.parse_known_args(argv)

    if rest and rest[0] == "evolution":
        sub = argparse.ArgumentParser(prog="chain_tracker.py evolution")
        sub.add_argument("action", choices=["list", "confirm", "reject"])
        sub.add_argument("proposal_id", nargs="?")
        sub_args = sub.parse_args(rest[1:])
        if sub_args.action in ("confirm", "reject") and not sub_args.proposal_id:
            sub.error(f"evolution {sub_args.action} 需要 <proposal_id>")
        return {"list": _cmd_evo_list, "confirm": _cmd_evo_confirm,
                "reject": _cmd_evo_reject}[sub_args.action](sub_args)
    if rest:
        p.error(f"未知参数/子命令: {' '.join(rest)}")
    return _cmd_scan(args)


if __name__ == "__main__":
    sys.exit(main())
