#!/usr/bin/env python3
"""鳄鱼派规则引擎实时数据适配（P2b）。

从 marketdata 统一数据源层取数，喂给 gator_rules 纯函数，输出当前判定。

用法：
    python scripts/gator_rules_snapshot.py           # 打印当前判定
    python scripts/gator_rules_snapshot.py --json    # JSON 输出（供 cron/agent 消费）

设计：docs/design/dual-school-architecture.md §3.4
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qing_investment.monitor.rules.gator_rules import (  # noqa: E402
    assess_emotion_ice,
    assess_hedge,
    assess_scissors,
    assess_stop_falling,
)

# 指数代码（marketdata 统一符号）
INDEX_CODES = {
    "sh_pct": "sh000001",      # 上证
    "cyb_pct": "sz399006",     # 创业板
    "hs300_pct": "sh000300",   # 沪深300
    "zz2000_pct": "sh000852",  # 中证2000
}


def _pct(snap: dict, code: str) -> float | None:
    quotes = snap.get("quotes") or []
    if isinstance(quotes, dict):
        quotes = list(quotes.values())
    for q in quotes:
        if not isinstance(q, dict):
            continue
        if q.get("code") == code:
            v = q.get("change_pct")
            if v is None:
                v = q.get("pct_change")
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


def collect_market_data() -> tuple[dict, list[str]]:
    """取指数涨跌幅。返回 (data, errors)。"""
    from qing_investment import marketdata as md

    errors: list[str] = []
    data: dict = {}
    try:
        snap = md.get_quotes(list(INDEX_CODES.values()))
        for key, code in INDEX_CODES.items():
            data[key] = _pct(snap, code)
        if snap.get("errors"):
            errors.append(f"部分指数取数失败: {snap['errors']}")
    except Exception as exc:  # 数据源全挂 → 明确报错，不编造
        errors.append(f"指数快照失败: {exc}")
        data = {k: None for k in INDEX_CODES}
    return data, errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    market, errs = collect_market_data()

    # 剪刀差复用同一快照
    scissors = assess_scissors(market.get("hs300_pct"), market.get("zz2000_pct"))

    # 止跌 5 信号：板块/券商/资金/基差数据源暂缺 → 对应项将判 UNKNOWN（诚实标注）
    stop = assess_stop_falling(
        market=market,
        sector=None,
        broker=None,
        fund=None,
        basis=None,
    )

    result = {
        "school": "gator",
        "market": market,
        "stop_falling": {
            "met": stop.met_count,
            "total": stop.total_count,
            "stance": stop.stance,
            "signals": [
                {"rule_id": s.rule_id, "name": s.name, "level": s.level.value, "detail": s.detail}
                for s in stop.signals
            ],
            "notes": stop.notes,
        },
        "scissors": {
            "level": scissors.level.value,
            "detail": scissors.detail,
        },
        "errors": errs,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("── 鳄鱼派规则判定（gator school）──")
    print(f"指数：{market}")
    print(f"\n止跌 5 信号：{stop.met_count}/{stop.total_count} → {stop.stance}")
    for s in stop.signals:
        mark = {"met": "✅", "not_met": "❌", "unknown": "❔"}[s.level.value]
        print(f"  {mark} {s.name}：{s.detail}")
    print(f"\n剪刀差：{scissors.detail}")
    for n in stop.notes:
        print(f"  · {n}")
    if errs:
        print("\n⚠️ 数据告警：")
        for e in errs:
            print(f"  {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
