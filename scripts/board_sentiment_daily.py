#!/usr/bin/env python3
"""板块情绪温度计日度编排（板块情绪温度计的主入口）。

流程：读 90 个 THS 行业板块日K（board_klines_all/）+ 最新龙虎榜（billboard/）
+ 最新融资明细（margin/，按 board_members 聚合到板块）→ compute_temperature
→ 冰封区板块惰性估值（valuation_overlay，3天缓存）
→ 落盘 infra/data/board_sentiment/YYYY-MM-DD.json
→ 与前一日 diff：有板块新跨入 hot(>=80)/cold(<=20) 区时 stdout 输出推送文本
（stdout 非空 = cron wrapper 投递飞书；无跨区则静默）。

手动: .venv/bin/python scripts/board_sentiment_daily.py [--date YYYYMMDD]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
KLINES_DIR = ROOT / "infra" / "data" / "board_klines_all"
BILLBOARD_DIR = ROOT / "infra" / "data" / "billboard"
MARGIN_DIR = ROOT / "infra" / "data" / "margin"
OUT_DIR = ROOT / "infra" / "data" / "board_sentiment"

from investment_engine.sentiment.thermometer import compute_temperature  # noqa: E402
from investment_engine.sentiment.board_members import get_stock_board_map  # noqa: E402


def _latest_file(d: Path) -> Path | None:
    files = sorted(d.glob("*.json"))
    return files[-1] if files else None


def load_board_klines() -> dict[str, list[dict]]:
    out = {}
    for p in KLINES_DIR.glob("industry_*.json"):
        name = p.stem[len("industry_"):]
        try:
            out[name] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return out


def load_billboard() -> dict[str, dict]:
    p = _latest_file(BILLBOARD_DIR)
    return json.loads(p.read_text(encoding="utf-8")) if p else {}


def load_margin_by_board(stock2board: dict[str, str]) -> tuple[dict, dict]:
    """返回 (板块当前融资余额合计, 板块20日变化率历史序列)。
    历史由每日文件累积：变化率序列 = 每个历史日的板块融资余额合计 → 20日变化率。"""
    import re
    files = sorted(f for f in MARGIN_DIR.glob("*.json")
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.stem))
    if not files:
        return {}, {}
    daily_totals: list[tuple[str, dict[str, float]]] = []
    for f in files[-60:]:  # 最多用 60 个交易日历史
        day: dict[str, float] = {}
        for code, v in json.loads(f.read_text(encoding="utf-8")).items():
            b = stock2board.get(code)
            if b:
                day[b] = day.get(b, 0.0) + float(v.get("rzye") or 0)
        daily_totals.append((f.stem, day))
    latest = daily_totals[-1][1]
    chg_hist: dict[str, list[float]] = {}
    for i in range(20, len(daily_totals)):
        prev, cur = daily_totals[i - 20][1], daily_totals[i][1]
        for b, v in cur.items():
            p = prev.get(b)
            if p and p > 0:
                chg_hist.setdefault(b, []).append((v / p - 1) * 100)
    return latest, chg_hist


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--no-valuation", action="store_true", help="跳过估值 overlay（快）")
    args = ap.parse_args()
    iso = f"{args.date[:4]}-{args.date[4:6]}-{args.date[6:]}"

    klines = load_board_klines()
    billboard = load_billboard()
    stock2board = get_stock_board_map()
    margin_now, margin_hist = load_margin_by_board(stock2board)
    print(f"板块K线 {len(klines)}，龙虎榜板块 {len(billboard)}，"
          f"融资历史板块 {len(margin_hist)}", file=sys.stderr)

    boards = []
    for name, bars in sorted(klines.items()):
        if len(bars) < 30:
            continue
        chg = None
        hist = margin_hist.get(name, [])
        cur = margin_now.get(name)
        if hist and cur:
            # 当前变化率 = 最近一条历史值（load_margin_by_board 已按日算好）
            chg = hist[-1]
        t = compute_temperature(bars, board_stats=billboard.get(name),
                                margin_chg=chg, margin_hist=hist)
        boards.append({"name": name, **t})

    hot = sorted((b for b in boards if b["zone"] == "hot"),
                 key=lambda x: -x["score"])[:5]
    cold_all = sorted((b for b in boards if b["zone"] == "cold"),
                      key=lambda x: x["score"])
    cold = cold_all[:5]

    # 估值 overlay：全部 cold 板块（2026-10-12 方案2：新跨区板块常在 TOP5 之外，
    # 只算 TOP5 会导致"新冷门"推送看不到便宜/冷但贵判定）。3天缓存控制成本。
    if not args.no_valuation:
        from investment_engine.sentiment.valuation_overlay import (
            assess_all_valuations,
        )
        # 并发批量：板块间 + 成分股内双层并行（2026-10-16 方案 B1）。
        # 串行版 31 cold 板块需 30-50 分钟，超过 cron 900s 窗口。
        val_map = assess_all_valuations([b["name"] for b in cold_all])
        for b in cold_all:
            v = val_map.get(b["name"]) or {"error": "missing"}
            b["valuation"] = v
            b["opportunity"] = bool(v.get("cheap"))
        # 回填到 boards 列表对应项
        for b in boards:
            if b["name"] in val_map:
                b["valuation"] = val_map[b["name"]]
                b["opportunity"] = bool(val_map[b["name"]].get("cheap"))

    result = {"date": iso, "n_boards": len(boards), "boards": boards,
              "hot_top5": hot, "cold_top5": cold}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{iso}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"落盘 {OUT_DIR / f'{iso}.json'}: {len(boards)} 板块, "
          f"hot={sum(1 for b in boards if b['zone'] == 'hot')}, "
          f"cold={sum(1 for b in boards if b['zone'] == 'cold')}", file=sys.stderr)

    # 跨区 diff 推送
    prev_files = sorted(OUT_DIR.glob("*.json"))
    prev_files = [p for p in prev_files if p.stem < iso]
    if prev_files:
        prev = {b["name"]: b["zone"] for b in
                json.loads(prev_files[-1].read_text(encoding="utf-8"))["boards"]}
        new_hot = [b for b in boards
                   if b["zone"] == "hot" and prev.get(b["name"]) != "hot"]
        new_cold = [b for b in boards
                    if b["zone"] == "cold" and prev.get(b["name"]) != "cold"]
        if new_hot or new_cold:
            lines = [f"📊 板块情绪极值提醒（{iso}）"]
            for b in new_hot:
                lines.append(f"🔥 人声鼎沸：{b['name']} 温度{b['score']}"
                             f"（量能分位{b['components']['volume']:.0f}）")
            for b in new_cold:
                v = b.get("valuation") or {}
                tag = ""
                if v.get("cheap") is True:
                    tag = f" ✅便宜({v['method']}={v['value']}%) → 逆向关注"
                elif v.get("cheap") is False:
                    tag = " ⚠️冷但贵，该冷"
                lines.append(f"🧊 无人问津：{b['name']} 温度{b['score']}{tag}")
            print("\n".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
