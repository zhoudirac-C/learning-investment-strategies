#!/usr/bin/env python
"""买入信号历史回测（v2.1 M0）：离线回放 BuySignalRuleEngine，统计命中率。

用法:
  python scripts/backtest_buy_signals.py --start 2026-03-01 --end 2026-07-31 \
      [--horizons 5,10,20] [--config-dir config/stock_monitor] \
      [--db infra/data/kline_cache.db] [--output logs/backtest_buy_signals_<date>.md]

只读 K 线缓存与配置 yaml，无网络调用；数据缺失如实标注，不编造。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.backtest.history import (
    build_quote_snapshot, coverage, get_klines_range, list_trading_days, quote_from_kline,
)
from investment_engine.backtest.hit_rate import forward_return, summarize
from qing_investment.monitor.context import load_monitor_config
from qing_investment.monitor.rules import BuySignalRuleEngine

_LOOKBACK_DAYS = 60  # 重建快照时给引擎的截至当日历史窗口


def load_universe(config_dir: Path) -> list[dict]:
    """标的池：stock_pool.yaml（新结构）。返回 [{"code": "000636.SZ", "name": ...}]。"""
    cfg = load_monitor_config(config_dir)
    pool = cfg.stock_pool or {}
    return [
        {"code": s["code"], "name": s.get("name", "")}
        for s in pool.get("stocks", [])
        if s.get("code")
    ]


def build_engine_config(config_dir: Path) -> dict:
    cfg = load_monitor_config(config_dir)
    return {
        "watchlist": cfg.watchlist or {},
        "stock_pool": cfg.stock_pool or {},
        "positions": cfg.positions or {},
        "strategy_pack": cfg.strategy_pack or {},
    }


def run_backtest(
    config_dir: Path,
    db_path: Path,
    start: str,
    end: str,
    horizons: tuple[int, ...] = (5, 10, 20),
) -> dict:
    engine = BuySignalRuleEngine()
    config = build_engine_config(config_dir)
    universe = load_universe(config_dir)
    days = list_trading_days(start, end, db_path)
    cov = coverage(db_path)

    records: list[dict] = []
    skipped: dict[str, int] = {}
    for day in days:
        quotes, kline_map = [], {}
        for stock in universe:
            bare = stock["code"].split(".")[0]
            lo, hi = cov.get(bare, (None, None))
            if lo is None or not (lo <= day <= hi):
                skipped[bare] = skipped.get(bare, 0) + 1
                continue
            hist = get_klines_range(bare, lo, day, db_path)[-_LOOKBACK_DAYS:]
            if not hist or hist[-1]["date"] != day:
                skipped[bare] = skipped.get(bare, 0) + 1
                continue
            quotes.append(quote_from_kline(stock["code"], stock["name"], hist[-1]))
            kline_map[bare] = hist
        if not quotes:
            continue
        alerts = engine.evaluate(config, build_quote_snapshot(quotes))
        for alert in alerts:
            # alert.stock_code 来自配置（'002371.SZ' 或裸码 '002371'），取首段为裸码
            bare = alert.stock_code.split(".")[0]
            # 前向收益需要信号日之后的数据：kline_map 只到当日，须另取前向区间
            klines = get_klines_range(bare, day, end, db_path)
            if not klines:
                klines = kline_map.get(bare) or []
            records.append({
                "code": alert.stock_code,
                "name": alert.stock_name,
                "date": day,
                "price": alert.price,
                "trigger": alert.trigger,
                "returns": {h: forward_return(klines, day, h) for h in horizons},
            })

    stats = summarize(records, horizons)
    return {
        "params": {"start": start, "end": end, "horizons": horizons,
                   "universe_size": len(universe), "trading_days": len(days)},
        "signals": records,
        "stats": {str(h): s for h, s in stats.items()},
        "skipped_no_data": skipped,
    }


def render_report(result: dict) -> str:
    p = result["params"]
    lines = [
        f"# 买入信号回测报告（{p['start']} ~ {p['end']}）",
        "",
        f"- 标的池: {p['universe_size']} 只（stock_pool.yaml）",
        f"- 回测交易日: {p['trading_days']} 天（以缓存实际数据为准）",
        f"- 信号总数: {len(result['signals'])}",
        "",
        "| horizon | 样本数 | 命中(收益>0) | 命中率 | 平均收益 |",
        "|---|---|---|---|---|",
    ]
    for h, s in result["stats"].items():
        rate = f"{s['hit_rate']:.1%}" if s["hit_rate"] is not None else "N/A"
        avg = f"{s['avg_return']:.2%}" if s["avg_return"] is not None else "N/A"
        lines.append(f"| {h}日 | {s['samples']} | {s['hits']} | {rate} | {avg} |")
    if result["skipped_no_data"]:
        lines += ["", "## 数据缺口（如实标注）", ""]
        for code, n in sorted(result["skipped_no_data"].items()):
            lines.append(f"- {code}: {n} 个交易日无缓存数据")
    lines += [
        "",
        "## 定性说明（必读）",
        "",
        "- 本报告回测的是**执行层规则**（stock_pool 介入区间 + 量价条件），"
        "不是 UP 观点本身，也不是推理模式；结果**不能作为方法论有效的证据**"
        "（方法论验证以 M1 盲测 / 影子双轨为准）。",
        "- 回测未加载 MarketGate（大盘窗口）/ SectorGate（板块阶段）两道前置门控，"
        "信号比生产环境宽松。",
        "- stock_pool 为当前快照，套用到历史日期存在前视偏差（方向不定）。",
        "- 「近3日缩量 / MA20上方」读缓存最新窗口，对历史信号日为冻结常量。",
        "",
        "> 数据时间戳: K线缓存 infra/data/kline_cache.db；本报告不构成投资建议。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="买入信号历史回测")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--horizons", default="5,10,20")
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    horizons = tuple(int(x) for x in args.horizons.split(","))
    result = run_backtest(
        Path(args.config_dir), Path(args.db), args.start, args.end, horizons
    )
    report = render_report(result)
    out = Path(args.output) if args.output else Path(
        f"logs/backtest_buy_signals_{date.today():%Y%m%d}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"信号数: {len(result['signals'])}; 报告: {out}")
    print(json.dumps(result["stats"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
