#!/usr/bin/env python
"""生成 pattern validation 回写提案（M1 盲测结果回填）。

用法: .venv/bin/python scripts/propose_pattern_validation.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml

from investment_engine.blindtest import score, truth as truth_mod
from investment_engine.pattern_eval.attribute import pattern_metrics
from investment_engine.pattern_eval.bucket import bucketize
from investment_engine.pattern_eval.proposal import build_proposal, write_proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 pattern validation 回写提案")
    parser.add_argument("--results", default="evals/blindtest/results.jsonl")
    parser.add_argument("--patterns", default="framework/reasoning-patterns.yaml")
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--out-dir", default="framework/proposals")
    args = parser.parse_args(argv)

    results = score.load_results(args.results)
    truth = truth_mod.load_truth(Path(args.db))
    metrics = pattern_metrics(
        results, truth=truth, config_dir=Path(args.config_dir),
        db_path=Path(args.db),
        direction_scorer=lambda rs: score.direction_scores(
            rs, config_dir=Path(args.config_dir), db_path=Path(args.db)),
        stock_scorer=lambda rs: score.stock_scores(rs, db_path=Path(args.db)),
    )
    doc = yaml.safe_load(Path(args.patterns).read_text(encoding="utf-8"))
    buckets = bucketize(metrics, [p["pattern_id"] for p in doc["patterns"]])
    window = {"start": results[0]["date"], "end": results[-1]["date"],
              "scored_days": len(results)}
    proposal = build_proposal(metrics, buckets, doc["patterns"], window=window)
    path = write_proposal(proposal, Path(args.out_dir))
    print(f"[proposal] {path}")
    for pid, b in buckets.items():
        print(f"  {pid}: {b['bucket']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
