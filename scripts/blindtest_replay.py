#!/usr/bin/env python
"""M1 盲测回放 CLI：--run 推理 / --score 评分 / --report 报告 / --up-baseline 对照。

用法:
  DEEPSEEK_API_KEY=... python scripts/blindtest_replay.py --run [--days N]
  python scripts/blindtest_replay.py --score --report
  DEEPSEEK_API_KEY=... python scripts/blindtest_replay.py --up-baseline [--up-days 10]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

DEFAULT_OUT = Path("evals/blindtest/results.jsonl")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M1 盲测回放")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--up-baseline", action="store_true")
    parser.add_argument("--days", type=int, default=None, help="只跑前 N 个交易日（dry-run 用）")
    parser.add_argument("--up-days", type=int, default=10)
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--start", default="2026-04-27")
    parser.add_argument("--end", default="2026-08-07")
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    from investment_engine.blindtest.dataset import trading_days
    from investment_engine.blindtest.truth import load_truth

    db = Path(args.db)
    out = Path(args.out)
    truth = load_truth(db_path=db)
    days = [d for d in trading_days(args.start, args.end, db) if truth.get(d)]
    if args.days:
        days = days[: args.days]
    print(f"测试集: {len(days)} 个交易日（{days[0] if days else '-'} ~ {days[-1] if days else '-'}）")

    if args.run:
        from investment_engine.blindtest.replay import run_replay

        stats = run_replay(days, config_dir=Path(args.config_dir), out_path=out,
                           db_path=db, model=args.model)
        print("回放:", stats)

    if args.score or args.report:
        from investment_engine.blindtest.score import (
            direction_scores, load_results, stage_accuracy, stock_scores,
        )

        results = load_results(out)
        stage = stage_accuracy(results, truth)
        dirs = direction_scores(results, config_dir=args.config_dir, db_path=db)
        stocks = stock_scores(results, db_path=db)
        print(f"阶段一致率: {_pct(stage['accuracy'])} (n={stage['samples']})")
        print(f"方向超额命中率: {_pct(dirs['hit_rate'])} (n={dirs['samples']})")
        print(f"标的超额命中率: {_pct(stocks['hit_rate'])} (n={stocks['samples']})")
        if args.report:
            report = _render_report(args, days, stage, dirs, stocks)
            rpt = Path(f"logs/m1-baseline-{date.today():%Y%m%d}.md")
            rpt.write_text(report, encoding="utf-8")
            print(f"报告: {rpt}")

    if args.up_baseline:
        from investment_engine.blindtest.score import load_results
        from investment_engine.blindtest.up_baseline import (
            build_comparison, extract_up_view, find_up_docs, pick_sample_days,
        )

        results = load_results(out)
        sample = pick_sample_days({d: truth[d] for d in days if d in truth}, n=args.up_days)
        views = {}
        for day in sample:
            docs = find_up_docs(day)
            if not docs:
                print(f"  [跳过] {day} 无 UP 当日文档")
                continue
            text = "\n\n".join(d.read_text(encoding="utf-8") for d in docs)
            views[day] = extract_up_view(text, model=args.model)
            print(f"  [{day}] UP stage={views[day]['stage']}")
        rows = build_comparison(results, truth, views)
        comp = Path(f"logs/m1-up-comparison-{date.today():%Y%m%d}.md")
        comp.write_text(_render_comparison(rows), encoding="utf-8")
        print(f"对照表: {comp}（{len(rows)} 天）")
    return 0


def _pct(v) -> str:
    return f"{v:.1%}" if v is not None else "N/A"


def _render_report(args, days, stage, dirs, stocks) -> str:
    lines = [
        f"# M1 盲测基线报告（{date.today():%Y-%m-%d}）",
        "",
        f"- 模型: {args.model}；窗口: {args.start} ~ {args.end}（{len(days)} 交易日）",
        "- 盲测约束: prompt 仅含当日可得客观数据，UP 言论不进 prompt（机械断言通过）",
        "",
        "## 主判据（vs 市场真值）",
        "",
        "| 指标 | 命中率 | 样本数 |",
        "|---|---|---|",
        f"| 市场阶段一致率 | {_pct(stage['accuracy'])} | {stage['samples']} |",
        f"| 方向 5 日超额命中率 | {_pct(dirs['hit_rate'])} | {dirs['samples']} |",
        f"| 标的 5 日超额命中率 | {_pct(stocks['hit_rate'])} | {stocks['samples']} |",
        "",
        "## 分环境段（按真值标签）",
        "",
        "| 阶段 | 样本 | 一致率 |",
        "|---|---|---|",
    ]
    for label, b in sorted(stage["by_label"].items()):
        lines.append(f"| {label} | {b['samples']} | {_pct(b['accuracy'])} |")
    lines += [
        "",
        "## Caveat",
        "",
        "- 单窗口 71 日，结论是基线而非毕业判据；",
        "- 板块资金流/涨停池无历史缓存，未进数据包；知识库为 2026-08-08 现版快照；",
        "- DeepSeek 知识截止与窗口的重叠情况见报告生成时的核查记录；",
        "- vs UP 对照见 logs/m1-up-comparison-*.md（诊断信息，不进命中率）。",
    ]
    return "\n".join(lines)


def _render_comparison(rows) -> str:
    lines = [
        "# M1 vs UP 对照表（诊断用，不进命中率）",
        "",
        "| 日期 | 真值 | AI | UP | verdict |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['date']} | {r['truth']} | {r['ai_stage']} | {r['up_stage'] or '-'} | {r['verdict']} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
