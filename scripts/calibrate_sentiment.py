#!/usr/bin/env python3
"""板块情绪温度历史校准（双锚点验证）。

锚点（2026-10-11 拍板）：
- 2024-09-23：全面冰点（9/24 政策转向前一天）→ 全市场中位温度应 <30
- 2024-10-08：全民沸腾（国庆后首日天量见顶）→ 中位温度应 >70，证券 >85
- 2025-04-07：关税暴跌冰点 → 中位温度应 <30

仅用量能+形态两分量（龙虎榜/融资历史数据未回填，权重自动归一化）。
数据源：infra/data/board_klines_all/（需已 --backfill-days 800 回填）。

用法: .venv/bin/python scripts/calibrate_sentiment.py
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
KLINES_DIR = ROOT / "infra" / "data" / "board_klines_all"

from investment_engine.sentiment.thermometer import compute_temperature  # noqa: E402

ANCHORS = ["2024-09-23", "2024-10-08", "2025-04-07", "2026-10-09"]
EXPECT = {"2024-09-23": ("<30", lambda m: m < 30),
          "2024-10-08": (">70", lambda m: m > 70),
          "2025-04-07": ("<30", lambda m: m < 30)}


def temperature_at(bars: list[dict], date: str) -> float | None:
    """用截至 date 的 bars 切片计算温度（只看量能+形态）。"""
    sliced = [b for b in bars if b["date"] <= date]
    if len(sliced) < 30 or sliced[-1]["date"] != date:
        return None  # 该日非交易日
    return compute_temperature(sliced)["score"]


def main() -> int:
    boards = {}
    for p in KLINES_DIR.glob("industry_*.json"):
        boards[p.stem[len("industry_"):]] = json.loads(p.read_text(encoding="utf-8"))
    print(f"加载 {len(boards)} 个板块")

    all_pass = True
    for date in ANCHORS:
        scores = {}
        for n, bars in boards.items():
            t = temperature_at(bars, date)
            if t is not None:
                scores[n] = t
        if not scores:
            print(f"\n=== {date}: 非交易日或无数据 ===")
            continue
        med = statistics.median(scores.values())
        p90 = sorted(scores.values())[int(len(scores) * 0.9)]
        p10 = sorted(scores.values())[int(len(scores) * 0.1)]
        hot = sum(1 for v in scores.values() if v >= 80)
        cold = sum(1 for v in scores.values() if v <= 20)
        top3 = sorted(scores.items(), key=lambda x: -x[1])[:3]
        bot3 = sorted(scores.items(), key=lambda x: x[1])[:3]
        exp = EXPECT.get(date)
        verdict = ""
        if exp:
            ok = exp[1](med)
            all_pass = all_pass and ok
            verdict = f" 预期中位{exp[0]} → {'✅通过' if ok else '❌不达标'}"
        print(f"\n=== {date} ==={verdict}")
        print(f"  中位 {med:.1f} | P10 {p10:.1f} | P90 {p90:.1f} | hot {hot} | cold {cold}")
        print(f"  最热: {[(n, round(v,1)) for n, v in top3]}")
        print(f"  最冷: {[(n, round(v,1)) for n, v in bot3]}")
        if "证券" in scores:
            print(f"  证券: {scores['证券']:.1f}")
    print(f"\n校准总体: {'✅ 全部锚点通过' if all_pass else '❌ 有锚点不达标，需调权重/参数'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
