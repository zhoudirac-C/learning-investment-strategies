#!/usr/bin/env python
"""涨停池入包 A/B 实验：同窗口、同 prompt（当前 PROMPT_VERSION），仅 limit_pool 有无两个臂。

背景：东财涨停池历史仅保留约 1 个月（实测边界 2026-07-27），无法回填至 M1 全窗口，
故改为子窗口对照实验：回答"涨停池进数据包是否提升命中率"。

用法:
  set -a; source .env; set +a
  .venv/bin/python scripts/blindtest_lp_ab.py [--start 2026-07-27] [--end 2026-08-07]
产物:
  evals/blindtest/ab-lp/with-lp.jsonl / without-lp.jsonl（断点续跑，重跑自动跳过已完成日）
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.blindtest import dataset
from investment_engine.blindtest.replay import run_replay
from investment_engine.blindtest.score import (
    direction_scores, load_results, stage_accuracy, stock_scores,
)
from investment_engine.blindtest.truth import load_truth

OUT_DIR = Path("evals/blindtest/ab-lp")


def _pct(v) -> str:
    return f"{v:.1%}" if v is not None else "N/A"


def _score(path: Path, truth, config_dir: str, db: Path) -> dict:
    results = load_results(path)
    return {
        "n_ok": len(results),
        "stage": stage_accuracy(results, truth),
        "dirs": direction_scores(results, config_dir=config_dir, db_path=db),
        "stocks": stock_scores(results, db_path=db),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="涨停池入包 A/B 实验")
    parser.add_argument("--start", default="2026-07-27")
    parser.add_argument("--end", default="2026-08-07")
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--model", default="deepseek-chat")
    args = parser.parse_args(argv)

    db = Path(args.db)
    truth = load_truth(db_path=db)
    days = [d for d in dataset.trading_days(args.start, args.end, db) if truth.get(d)]
    print(f"A/B 窗口: {len(days)} 个交易日（{days[0]} ~ {days[-1]}）")

    with_lp = OUT_DIR / "with-lp.jsonl"
    without_lp = OUT_DIR / "without-lp.jsonl"

    stats = run_replay(days, config_dir=Path(args.config_dir), out_path=with_lp,
                       db_path=db, model=args.model)
    print("with-lp 回放:", stats)

    # 对照臂：LP_ROOT 指向空目录 → pack 无 limit_pool 块（其余与处理臂完全一致）
    empty_lp = Path(tempfile.mkdtemp(prefix="empty_lp_"))
    orig = dataset.LP_ROOT
    dataset.LP_ROOT = empty_lp
    try:
        stats = run_replay(days, config_dir=Path(args.config_dir), out_path=without_lp,
                           db_path=db, model=args.model)
        print("without-lp 回放:", stats)
    finally:
        dataset.LP_ROOT = orig

    a = _score(with_lp, truth, args.config_dir, db)
    b = _score(without_lp, truth, args.config_dir, db)
    print("\n| 指标 | with-lp | without-lp |")
    print("|---|---|---|")
    print(f"| 有效样本日 | {a['n_ok']} | {b['n_ok']} |")
    print(f"| 阶段一致率 | {_pct(a['stage']['accuracy'])} (n={a['stage']['samples']}) "
          f"| {_pct(b['stage']['accuracy'])} (n={b['stage']['samples']}) |")
    print(f"| 方向5日超额命中率 | {_pct(a['dirs']['hit_rate'])} (n={a['dirs']['samples']}) "
          f"| {_pct(b['dirs']['hit_rate'])} (n={b['dirs']['samples']}) |")
    print(f"| 标的5日超额命中率 | {_pct(a['stocks']['hit_rate'])} (n={a['stocks']['samples']}) "
          f"| {_pct(b['stocks']['hit_rate'])} (n={b['stocks']['samples']}) |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
