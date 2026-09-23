#!/usr/bin/env python3
"""雪球大牛回测 P1：板块启动事件库扫描器

设计：docs/design/xueqiu-expert-backtest-design.md §4.1
板块体系：同花顺（akshare）行业 881xxx(90) + 概念 30xxxx(375)
事件判定（已拍板 2026-09-23）：
  ① 收盘上穿 MA60（当日 close > MA60 且前一日 ≤ MA60）
  ② 之后 20 个交易日内收盘最大涨幅 > 20%

用法：
  python scripts/xueqiu_expert/sector_launch_scan.py            # 全量扫描（断点续跑）
  python scripts/xueqiu_expert/sector_launch_scan.py --limit 5  # 试跑前 5 个板块
  python scripts/xueqiu_expert/sector_launch_scan.py --verify   # 抽样公认行情验收
产出：
  data/xueqiu/sector_klines/{code}.json   # 板块日K缓存（断点续跑用）
  data/xueqiu/sector_launches.json        # 启动事件库
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

KLINE_DIR = REPO / "data" / "xueqiu" / "sector_klines"
OUT_PATH = REPO / "data" / "xueqiu" / "sector_launches.json"
START_DATE = "20240601"  # MA60 预热：从 2024-06 拉，保证 2024-09 起 MA60 有值
END_DATE = "20260923"
GAIN_THRESHOLD = 20.0    # 已拍板：20 日最大涨幅 > 20%
FORWARD_DAYS = 20
SLEEP = 0.6              # akshare ths 限流间隔


def load_board_lists() -> list[dict]:
    """THS 行业 + 概念板块全量列表。"""
    import akshare as ak
    boards = []
    ind = ak.stock_board_industry_name_ths()
    for _, r in ind.iterrows():
        boards.append({"name": r["name"], "code": str(r["code"]), "kind": "industry"})
    con = ak.stock_board_concept_name_ths()
    for _, r in con.iterrows():
        boards.append({"name": r["name"], "code": str(r["code"]), "kind": "concept"})
    return boards


def fetch_kline(board: dict) -> list[dict] | None:
    """单板块日K（带缓存）。返回 [{date, close, high, ...}] 升序。"""
    cache = KLINE_DIR / f"{board['code']}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    import akshare as ak
    try:
        if board["kind"] == "industry":
            df = ak.stock_board_industry_index_ths(
                symbol=board["name"], start_date=START_DATE, end_date=END_DATE)
        else:
            df = ak.stock_board_concept_index_ths(
                symbol=board["name"], start_date=START_DATE, end_date=END_DATE)
    except Exception as e:  # noqa: BLE001
        print(f"  [WARN] {board['name']}({board['code']}) 拉取失败: {type(e).__name__} {str(e)[:80]}")
        return None
    if df is None or len(df) == 0:
        print(f"  [WARN] {board['name']}({board['code']}) 空数据")
        return None
    bars = [{"date": str(r["日期"]), "open": float(r["开盘价"]), "high": float(r["最高价"]),
             "low": float(r["最低价"]), "close": float(r["收盘价"]),
             "volume": float(r["成交量"]), "amount": float(r["成交额"])}
            for _, r in df.iterrows()]
    cache.write_text(json.dumps(bars, ensure_ascii=False))
    return bars


def detect_launches(board: dict, bars: list[dict]) -> list[dict]:
    """v3 口径（2026-09-23 数据校准后锁定）：启动日 = 波段低点。

    对每个交易日 j 回看 20 天找最低点 low：若 (close[j]/low - 1) > 阈值，
    则低点日记为一个启动事件；同一启动日的多个峰值合并（取最大涨幅）；
    相邻 ≤8 天的启动日视为同一波段合并（保留涨幅大者）。

    口径演进：
    - v1（MA60 上穿）：只能捕捉底部反转，2025 年均线上方的主升浪全部漏掉
      （实测 2025-03/07/09 月份事件≈0），被数据证伪。
    - v2（20 日前瞻涨幅起点）：起点语义错误，8 月事件把 9/24 行情"吃掉"。
    - v3（峰值回看波段低点）：启动日语义正确，验收清单命中率最高。
    """
    closes = [b["close"] for b in bars]
    dates = [b["date"] for b in bars]
    by_launch: dict[int, dict] = {}
    for j in range(5, len(closes)):
        lb = max(0, j - FORWARD_DAYS)
        seg = closes[lb:j]
        low = min(seg)
        li = lb + seg.index(low)
        gain = (closes[j] / low - 1.0) * 100.0
        if gain > GAIN_THRESHOLD:
            if li not in by_launch or gain > by_launch[li]["max_gain_20d"]:
                by_launch[li] = {
                    "sector": board["name"], "code": board["code"], "kind": board["kind"],
                    "launch_date": dates[li], "close_at_launch": low,
                    "peak_date": dates[j], "max_gain_20d": round(gain, 2)}
    evs = sorted(by_launch.values(), key=lambda e: e["launch_date"])
    merged: list[dict] = []
    for e in evs:
        if merged and (int(e["launch_date"].replace("-", ""))
                       - int(merged[-1]["launch_date"].replace("-", ""))) <= 8:
            if e["max_gain_20d"] > merged[-1]["max_gain_20d"]:
                merged[-1] = e
            continue
        merged.append(e)
    return merged


def _detect_with_threshold(board: dict, bars: list[dict], threshold: float) -> list[dict]:
    """detect_launches 的参数化阈值版本（recalc --threshold 用）。"""
    global GAIN_THRESHOLD
    saved = GAIN_THRESHOLD
    GAIN_THRESHOLD = threshold
    try:
        return detect_launches(board, bars)
    finally:
        GAIN_THRESHOLD = saved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只扫前 N 个板块（试跑）")
    ap.add_argument("--verify", action="store_true", help="验收模式：抽样公认行情核对")
    ap.add_argument("--recalc", action="store_true",
                    help="本地重算模式：不重拉K线，从缓存重新判定全部事件")
    ap.add_argument("--threshold", type=float, default=GAIN_THRESHOLD,
                    help="涨幅阈值（默认 20，对比分析用）")
    args = ap.parse_args()

    KLINE_DIR.mkdir(parents=True, exist_ok=True)

    if args.verify:
        verify()
        return

    if args.recalc:
        # 从缓存重算：需要 code→{name,kind} 映射（从现有事件库或板块列表）
        boards = _boards_from_cache()
        threshold = args.threshold
        all_events: list[dict] = []
        for board in boards:
            cache = KLINE_DIR / f"{board['code']}.json"
            if not cache.exists():
                continue
            bars = json.loads(cache.read_text())
            all_events.extend(_detect_with_threshold(board, bars, threshold))
        all_events.sort(key=lambda e: (e["launch_date"], e["sector"]))
        OUT_PATH.write_text(json.dumps(all_events, ensure_ascii=False, indent=1))
        print(f"重算完成: {len(boards)} 板块 → {len(all_events)} 事件（阈值 {threshold}%）→ {OUT_PATH}")
        return

    boards = load_board_lists()
    if args.limit:
        boards = boards[:args.limit]
    print(f"板块总数: {len(boards)}")

    all_events: list[dict] = []
    if OUT_PATH.exists():
        all_events = json.loads(OUT_PATH.read_text())
        print(f"已有事件库: {len(all_events)} 条（增量合并）")
    done_codes = {e["code"] for e in all_events}

    n_ok, n_fail = 0, 0
    for idx, board in enumerate(boards, 1):
        if board["code"] in done_codes:
            continue
        bars = fetch_kline(board)
        if bars is None:
            n_fail += 1
            time.sleep(SLEEP)
            continue
        events = detect_launches(board, bars)
        all_events.extend(events)
        n_ok += 1
        if events:
            print(f"  [{idx}/{len(boards)}] {board['name']}: {len(events)} 个启动事件 "
                  f"(最近: {events[-1]['launch_date']} +{events[-1]['max_gain_20d']}%)")
        if idx % 20 == 0:
            print(f"  ...进度 {idx}/{len(boards)}，累计事件 {len(all_events)}")
            OUT_PATH.write_text(json.dumps(all_events, ensure_ascii=False, indent=1))
        time.sleep(SLEEP)

    OUT_PATH.write_text(json.dumps(all_events, ensure_ascii=False, indent=1))
    print(f"\n完成: 板块 {n_ok} 成功 / {n_fail} 失败，事件库 {len(all_events)} 条 → {OUT_PATH}")


# 公认行情验收清单：板块名关键词 + 启动日应落入的月份窗口
# 板块名按同花顺实际叫法校准（2026-09-23：光模块→CPO、DeepSeek→算力/AI类、稀土→稀土永磁）
VERIFY_CASES = [
    ("创新药", "2025-04", "2025-06"),
    ("存储", "2025-06", "2025-10"),
    ("CPO", "2025-06", "2025-09"),
    ("稀土永磁", "2025-06", "2025-08"),
    ("机器人", "2025-01", "2025-02"),
    ("证券", "2024-09", "2024-10"),
    ("算力", "2025-01", "2025-02"),
    ("半导体", "2025-08", "2025-10"),
    ("固态电池", "2026-04", "2026-07"),
    ("数据中心", "2025-01", "2025-02"),
]


def _boards_from_cache() -> list[dict]:
    """从已有事件库恢复 code→{name,kind} 映射（recalc 模式用）。"""
    if OUT_PATH.exists():
        seen: dict[str, dict] = {}
        for e in json.loads(OUT_PATH.read_text()):
            seen[e["code"]] = {"name": e["sector"], "code": e["code"], "kind": e["kind"]}
        if seen:
            return list(seen.values())
    # 兜底：事件库不存在时重新拉列表（走网络）
    return load_board_lists()


def verify() -> None:
    events = json.loads(OUT_PATH.read_text())
    hits, misses = [], []
    for kw, m_start, m_end in VERIFY_CASES:
        matched = [e for e in events
                   if kw in e["sector"] and m_start <= e["launch_date"][:7] <= m_end]
        if matched:
            hits.append(f"  ✅ {kw}: {matched[0]['sector']} @ {matched[0]['launch_date']} (+{matched[0]['max_gain_20d']}%)")
        else:
            misses.append(f"  ❌ {kw}: 期望 {m_start}~{m_end} 有启动事件，未命中")
    print(f"验收: {len(hits)}/{len(VERIFY_CASES)} 命中（要求 ≥8/10）")
    for line in hits + misses:
        print(line)


if __name__ == "__main__":
    main()
