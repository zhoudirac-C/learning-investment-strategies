#!/usr/bin/env python
"""claims 分桶 vs 市场评分（主计划 §12，evaluate_agent_vs_up 的面向市场替代版，M3 基建 v1）。

口径：
- claims 臂：五桶（up/agent/research/announcement/data）× claim_type × status 统计。
  市场命中率需要"市场结果回写"字段（outcome 类），当前 claims 库无此字段——
  各桶一律标 insufficient_data，这正是 M3 待落地的回写机制本身，不虚构数字。
- agent 臂（预览）：复用 shadow 到期结算（evals/shadow/predictions，机械真值 +
  5 日超额），作为 agent 桶的市场评分占位；正式 agent claims 回路待 AI 自产 claims 入库。

用法: .venv/bin/python scripts/evaluate_vs_market.py [--report]
产物: 终端表格；--report 时写 logs/claims-vs-market-YYYYMMDD.md
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.claim_buckets import BUCKETS, load_claims
from investment_engine.shadow.graduation import aggregate, load_records

NO_OUTCOME_NOTE = (
    "claims 库无市场结果回写字段（outcome），命中率不可计算——"
    "待 M3 回写机制（市场结果→置信度）落地后本表自动出数。"
)


def _pct(v) -> str:
    return f"{v:.1%}" if v is not None else "N/A"


def bucket_stats(claims: list[dict]) -> dict:
    """每桶 n / status 分布 / claim_type 分布。"""
    by_bucket: dict[str, list[dict]] = {b: [] for b in BUCKETS}
    for c in claims:
        by_bucket.setdefault(c["bucket"], []).append(c)
    return {
        b: {
            "n": len(rs),
            "status": Counter(r["status"] or "(missing)" for r in rs),
            "claim_type": Counter(r["claim_type"] or "(missing)" for r in rs),
        }
        for b, rs in by_bucket.items()
    }


def shadow_agent_arm(pred_dir: Path) -> dict:
    """agent 桶预览：shadow 到期结算聚合（阶段/方向/标的）。"""
    records, skipped = load_records(Path(pred_dir))
    agg = aggregate(records)
    stock_hits = stock_n = 0
    for r in records:
        if r.get("status") == "scored":
            st = (r.get("due_scores") or {}).get("stocks") or {}
            stock_n += st.get("samples", 0)
            stock_hits += st.get("hits", 0)
    agg["stock"] = {"rate": stock_hits / stock_n if stock_n else None, "n": stock_n}
    return {"records": len(records), "skipped": skipped, **agg}


def render(stats: dict, total: int, skipped: int, arm: dict) -> str:
    lines = [
        f"claims 总数 {total}（解析失败文件 {skipped}）",
        "",
        "## 分桶 × 状态（市场命中率列：%s）" % NO_OUTCOME_NOTE,
        "",
        "| 桶 | n | status 分布 | 市场命中率 |",
        "|---|---|---|---|",
    ]
    for b in BUCKETS:
        s = stats[b]
        if s["n"] == 0:
            continue
        dist = ", ".join(f"{k}:{v}" for k, v in s["status"].most_common())
        lines.append(f"| {b} | {s['n']} | {dist} | insufficient_data |")
    lines += ["", "## 分桶 × claim_type（UP 画像骨架：哪类观点多）", ""]
    for b in BUCKETS:
        s = stats[b]
        if s["n"] == 0:
            continue
        top = ", ".join(f"{k}:{v}" for k, v in s["claim_type"].most_common(8))
        lines.append(f"- **{b}**（n={s['n']}）: {top}")
    lines += [
        "",
        "## agent 臂（shadow 盲判到期结算，机械真值 + 5 日超额口径）",
        "",
        f"- 预测记录 {arm['records']} 天（跳过 {arm['skipped']}）",
        f"- 阶段一致率 {_pct(arm['stage']['rate'])}（n={arm['stage']['n']}，"
        "与机械真值一致性检查，非预测力证据）",
        f"- 方向 5 日超额命中 {_pct(arm['direction']['rate'])}（n={arm['direction']['n']}）",
        f"- 标的 5 日超额命中 {_pct(arm['stock']['rate'])}（n={arm['stock']['n']}）",
        "",
        "口径声明：agent 臂 = 盲判轻管线（shadow）；up/research 等桶待回写机制后同表出数。"
        "up 桶含缠论课程卡片（sources/chanlun，教材性质，technical-knowledge 类不参与市场命中率）。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="claims 分桶 vs 市场评分")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--claims-dir", default="knowledge/claims")
    parser.add_argument("--pred-dir", default="evals/shadow/predictions")
    args = parser.parse_args(argv)

    claims, skipped = load_claims(Path(args.claims_dir))
    stats = bucket_stats(claims)
    arm = shadow_agent_arm(Path(args.pred_dir))
    text = render(stats, len(claims), skipped, arm)
    print(text)

    other = stats.get("other", {"n": 0})
    if other["n"]:
        print(f"\n[提示] other 桶 {other['n']} 张（未识别来源，需评审映射表）")

    if args.report:
        out = Path("logs") / f"claims-vs-market-{date.today():%Y%m%d}.md"
        out.write_text(f"# claims 分桶 vs 市场（{date.today()}）\n\n" + text + "\n",
                       encoding="utf-8")
        print(f"\n报告已写 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
