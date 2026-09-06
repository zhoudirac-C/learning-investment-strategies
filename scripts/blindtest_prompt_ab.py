#!/usr/bin/env python
"""盲判 prompt A/B 实验：同窗口、同数据包、同校验层，仅 system prompt 版本不同。

本轮（2026-09-05 二轮）：v15 经验补丁版 vs v17（v16 归因修复版——direction_pool
精选池回 pack、引用义务清单化、方向硬门槛逐条）。两臂均走 run_with_validation
（与生产 shadow_predict 同路径），可对比确定性校验重试率与首版违规分布。

用法:
  set -a; source .env; set +a
  .venv/bin/python scripts/blindtest_prompt_ab.py [--start 2026-08-03] [--end 2026-08-28]
产物:
  evals/blindtest/ab-prompt-v17/{v15,v17}.jsonl（断点续跑，重跑自动跳过已完成日）
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.blindtest import dataset
from investment_engine.blindtest.replay import (
    DEFAULT_MODEL, SYSTEM_PROMPT_V15, SYSTEM_PROMPT_V16, SYSTEM_PROMPT_V17,
    SYSTEM_PROMPT_V18, run_replay,
)
from investment_engine.blindtest.score import (
    direction_scores, load_results, stage_accuracy, stock_scores,
)
from investment_engine.blindtest.truth import load_truth

OUT_DIR = Path("evals/blindtest/ab-prompt-v17")
ALL_ARMS = {"v15": SYSTEM_PROMPT_V15, "v16": SYSTEM_PROMPT_V16,
            "v17": SYSTEM_PROMPT_V17, "v18": SYSTEM_PROMPT_V18}


def _pct(v) -> str:
    return f"{v:.1%}" if v is not None else "N/A"


def _score(path: Path, truth, config_dir: str, db: Path) -> dict:
    results = load_results(path)
    retried = 0
    violations: Counter = Counter()
    for r in results:
        v = r.get("validation") or {}
        if v.get("retried"):
            retried += 1
        for item in v.get("violations") or []:
            violations[str(item).split(":")[0]] += 1
        # 首版违规（重试后通过的那些）也要统计——否则看不到真实违规率
        for item in v.get("first_violations") or []:
            violations["首版" + str(item).split(":")[0]] += 1
    return {
        "n_ok": len(results),
        "stage": stage_accuracy(results, truth),
        "dirs": direction_scores(results, config_dir=config_dir, db_path=db),
        "stocks": stock_scores(results, db_path=db),
        "retried": retried,
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="盲判 prompt A/B 实验（v15 vs v17）")
    parser.add_argument("--start", default="2026-08-03")
    parser.add_argument("--end", default="2026-08-28")
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--arms", default="v15,v18",
                        help="逗号分隔的 prompt 版本（可选：" + "/".join(ALL_ARMS) + "）")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    arms = {k: ALL_ARMS[k] for k in args.arms.split(",")}

    db = Path(args.db)
    truth = load_truth(db_path=db)
    days = [d for d in dataset.trading_days(args.start, args.end, db) if truth.get(d)]
    print(f"A/B 窗口: {len(days)} 个交易日（{days[0]} ~ {days[-1]}）")
    for ver, prompt in arms.items():
        print(f"  {ver}: system prompt {len(prompt)} 字符")

    scores = {}
    for ver, prompt in arms.items():
        out = out_dir / f"{ver}.jsonl"
        stats = run_replay(days, config_dir=Path(args.config_dir), out_path=out,
                           db_path=db, model=args.model,
                           system_prompt=prompt, prompt_version=ver,
                           use_validation=True)
        print(f"{ver} 回放:", stats)

    for ver in arms:
        scores[ver] = _score(out_dir / f"{ver}.jsonl", truth, args.config_dir, db)

    print("\n| 指标 | " + " | ".join(arms) + " |")
    print("|---|" + "---|" * len(arms))
    rows = [
        ("有效样本日", lambda s: str(s["n_ok"])),
        ("阶段一致率", lambda s: f"{_pct(s['stage']['accuracy'])} (n={s['stage']['samples']})"),
        ("方向5日超额命中率", lambda s: f"{_pct(s['dirs']['hit_rate'])} (n={s['dirs']['samples']})"),
        ("标的5日超额命中率", lambda s: f"{_pct(s['stocks']['hit_rate'])} (n={s['stocks']['samples']})"),
        ("校验重试日数", lambda s: str(s["retried"])),
    ]
    for name, fmt in rows:
        print(f"| {name} | " + " | ".join(fmt(scores[v]) for v in arms) + " |")
    for ver in arms:
        if scores[ver]["violations"]:
            print(f"\n{ver} 违规分布: {json.dumps(dict(scores[ver]['violations']), ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
