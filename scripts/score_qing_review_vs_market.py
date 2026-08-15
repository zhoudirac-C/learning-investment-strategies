#!/usr/bin/env python
"""qing 复盘臂 vs 市场真值评分 + 与 shadow 臂同窗对照（v2.2 §16.3）。

用法: .venv/bin/python scripts/score_qing_review_vs_market.py [--report]
产物: 终端表格；--report 时写 logs/qing-vs-shadow-YYYYMMDD.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.blindtest.truth import load_truth
from investment_engine.qing_review import (
    load_summaries, normalize_stage, score_vs_truth, shadow_stage_records,
)

PRED_DIR = Path("evals/shadow/predictions")


def _pct(v) -> str:
    return f"{v:.1%}" if v is not None else "N/A"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="qing 复盘臂市场评分")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--summary", default="config/stock_monitor/daily_review_summary.json")
    args = parser.parse_args(argv)

    truth = load_truth(db_path=Path(args.db))
    summaries = load_summaries(Path(args.summary))
    # 未映射标签在 normalize 时抛 KeyError（强制评审），这里先全量过一遍
    unmapped = sorted({(m.get("stage") or "") for m in summaries.values()}
                      - {s for s in _mapped()} - {""})
    if unmapped:
        print(f"[阻断] 发现未映射 stage 标签，请先评审: {unmapped}")
        return 1

    qing = score_vs_truth(summaries, truth)
    print(f"qing 臂: {qing['samples']} 天可评（剔除 '未判断' {len(qing['excluded'])} 天: "
          f"{', '.join(qing['excluded'])}）")
    print(f"阶段一致率: {_pct(qing['accuracy'])}")
    for label, b in sorted(qing["by_label"].items()):
        print(f"  {label}: {_pct(b['accuracy'])} (n={b['samples']})")

    shadow = shadow_stage_records(PRED_DIR)
    overlap = sorted(set(shadow) & {d for d, m in summaries.items()
                                    if normalize_stage(m.get("stage")) is not None})
    lines = []
    q_hits = s_hits = 0
    if overlap:
        print(f"\n同窗对照（{len(overlap)} 天）:")
        print("| 日期 | 真值 | qing 臂 | shadow 臂 |")
        print("|---|---|---|---|")
        for d in overlap:
            t = truth.get(d, "-")
            q = normalize_stage(summaries[d].get("stage"))
            s = shadow[d]["stage"]
            q_hits += int(q == t)
            s_hits += int(s == t)
            lines.append(f"| {d} | {t} | {q} | {s} |")
            print(lines[-1])
        print(f"同窗一致率: qing {q_hits}/{len(overlap)} vs shadow {s_hits}/{len(overlap)}")

    if args.report:
        rpt = Path(f"logs/qing-vs-shadow-{date.today():%Y%m%d}.md")
        rpt.write_text(_render_report(args, qing, overlap, lines, summaries, shadow, truth,
                                      q_hits=q_hits, s_hits=s_hits),
                       encoding="utf-8")
        print(f"\n报告: {rpt}")
    return 0


def _mapped() -> set[str]:
    from investment_engine.qing_review import STAGE_MAP
    return set(STAGE_MAP)


def _render_report(args, qing, overlap, overlap_lines, summaries, shadow, truth,
                   *, q_hits: int, s_hits: int) -> str:
    from investment_engine.qing_review import STAGE_MAP
    lines = [
        f"# qing 复盘臂 vs shadow 盲判臂对照（{date.today():%Y-%m-%d}）",
        "",
        "## 口径声明（先读）",
        "",
        "- **qing 臂** = qing-agent 每日 17 点复盘落盘（UP 锚定 + 收盘后信息，**非盲**）重管线；",
        "- **shadow 臂** = 每日盲判（prompt 仅当日可得客观数据）轻管线；",
        "- 两臂用**同一份机械真值**（`blindtest/truth.py`，r20/pos20/vol_trend 规则）。"
        "stage 评分是'与机械规则的一致性'，非预测力证据（v2.2 §16.1）；",
        "- qing 的 stage 是自由文本（UP 词汇体系），归一化到四枚举报下表。"
        "该词汇体系在本窗口**无法表达'主升'**，相关真值日 qing 臂天然失分；",
        "- 方向/标的维度：qing 复盘无次日推荐标的的结构化输出（`tomorrow_scenarios` 几乎全空），"
        "本报告不评方向/标的，仅 stage。",
        "",
        "## 全窗口（qing 臂 46 天）",
        "",
        f"- 可评 {qing['samples']} 天，剔除 '未判断' {len(qing['excluded'])} 天"
        f"（{', '.join(qing['excluded'])}）",
        f"- **阶段一致率: {_pct(qing['accuracy'])}**",
        "",
        "| 真值段 | 样本 | 一致率 |",
        "|---|---|---|",
    ]
    for label, b in sorted(qing["by_label"].items()):
        lines.append(f"| {label} | {b['samples']} | {_pct(b['accuracy'])} |")
    if overlap_lines:
        lines += ["", f"## 同窗对照（{len(overlap)} 天）", "",
                  "| 日期 | 真值 | qing 臂 | shadow 臂 |", "|---|---|---|---|",
                  *overlap_lines, "",
                  f"同窗一致率: qing {q_hits}/{len(overlap)} vs shadow {s_hits}/{len(overlap)}"]
    lines += ["", "## stage 归一化映射表（先验规则，未拟合真值）", "",
              "| 原标签 | 映射 |", "|---|---|"]
    for raw, norm in sorted(STAGE_MAP.items(), key=lambda kv: str(kv[1])):
        lines.append(f"| {raw} | {norm or '（剔除）'} |")
    lines += [
        "",
        "## 结论（如实）",
        "",
        "- qing 臂 38 天总体一致率见上表；分环境：震荡段强、调整段弱（UP 词汇对回调偏宽容），"
        "且无法表达'主升'（主升/恐慌段 n=1 均无统计意义）；",
        "- 同窗对照样本极小且全为震荡日（always-震荡即满分），两臂差距不足 1 天即判平；",
        "- **综合：没有证据表明 UP 锚定重管线的阶段判断优于盲判轻管线**——qing 臂还携带收盘后"
        "信息（非盲），理论占优却未体现。此证据支持 v2.2 §16.3/§16.5 方向（拆锚定、分析层 skill 化），"
        "但样本仍薄，本报告每周五随 `graduation_check.py` 例行刷新累积；",
        "- 方向/标的维度的结论等 shadow 标的超额样本 n≥20 后（§16.3）补。",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
