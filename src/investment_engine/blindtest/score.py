"""盲测评分：阶段一致率 + 方向/标的 5 日相对沪深300 超额。"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.backtest.history import get_index_daily, get_klines_range
from investment_engine.backtest.hit_rate import forward_return

BENCH_CODE = "IDX000300"


def load_results(path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("ok"):
            rows.append(r)
    return rows


def stage_accuracy(results: list[dict], truth: dict[str, str]) -> dict:
    """truth: {date: label}。只在有真值的日期上评分。"""
    hits = 0
    by_label: dict[str, dict] = {}
    samples = 0
    for r in results:
        label = truth.get(r["date"])
        if label is None:
            continue
        samples += 1
        bucket = by_label.setdefault(label, {"samples": 0, "hits": 0})
        bucket["samples"] += 1
        if r["result"].get("market_stage") == label:
            hits += 1
            bucket["hits"] += 1
    for b in by_label.values():
        b["accuracy"] = b["hits"] / b["samples"] if b["samples"] else None
    return {
        "samples": samples, "hits": hits,
        "accuracy": hits / samples if samples else None,
        "by_label": by_label,
    }


def _forward(db_path, code: str, day: str, horizon: int) -> float | None:
    # 指数（IDX 别名）读 index_klines 表，个股读 stocks_kline 表
    from investment_engine.backtest.history import INDEX_ALIAS_TO_CODE
    if code in INDEX_ALIAS_TO_CODE:
        klines = get_index_daily(code, day, "2999-12-31", db_path=db_path)
    else:
        klines = get_klines_range(code, day, "2999-12-31", db_path=db_path)
    return forward_return(klines, day, horizon)


def _direction_members(config_dir, direction_id: str) -> list[str]:
    """方向 → 成分股代码列表。

    优先查 TDX 概念板块成分股（config/stock_monitor/sector_members.json），
    回退本地 stock_pool 的 direction 字段。direction_id 既可能是 TDX 板块名
    （如"算力租赁"），也可能是本地 direction_pool 的 id（如"mlcc_super_cycle"）。
    """
    # 1) TDX 板块成分股
    try:
        from investment_engine.blindtest.dataset import _load_sector_members
        members = _load_sector_members().get(direction_id)
        if members:
            return [c for c in members if c]
    except Exception:  # noqa: BLE001 - 无落盘 JSON 时回退
        pass

    # 2) 本地 stock_pool
    from qing_investment.monitor.context import load_monitor_config

    cfg = load_monitor_config(Path(config_dir))
    return [
        s["code"] for s in (cfg.stock_pool or {}).get("stocks", [])
        if s.get("direction") == direction_id and s.get("code")
    ]


def direction_scores(results: list[dict], *, config_dir, db_path=None,
                     bench_code: str = BENCH_CODE, horizon: int = 5) -> dict:
    hits = samples = 0
    details = []
    for r in results:
        for d in r["result"].get("directions", []):
            members = _direction_members(config_dir, d["direction_id"])
            rets = [
                v for v in (_forward(db_path, c, r["date"], horizon) for c in members)
                if v is not None
            ]
            bench = _forward(db_path, bench_code, r["date"], horizon)
            if not rets or bench is None:
                continue
            dir_ret = sum(rets) / len(rets)
            hit = (dir_ret - bench) > 1e-9  # 严格正超额；eps 挡浮点尾差
            samples += 1
            hits += int(hit)
            details.append({"date": r["date"], "direction_id": d["direction_id"],
                            "dir_ret": dir_ret, "bench_ret": bench, "hit": hit})
    return {"samples": samples, "hits": hits,
            "hit_rate": hits / samples if samples else None, "details": details}


def stock_scores(results: list[dict], *, db_path=None,
                 bench_code: str = BENCH_CODE, horizon: int = 5) -> dict:
    hits = samples = 0
    details = []
    for r in results:
        bench = _forward(db_path, bench_code, r["date"], horizon)
        if bench is None:
            continue
        for d in r["result"].get("directions", []):
            for code in d.get("stocks", []):
                ret = _forward(db_path, code, r["date"], horizon)
                if ret is None:
                    continue
                hit = (ret - bench) > 1e-9  # 严格正超额；eps 挡浮点尾差
                samples += 1
                hits += int(hit)
                details.append({"date": r["date"], "code": code,
                                "ret": ret, "bench_ret": bench, "hit": hit})
    return {"samples": samples, "hits": hits,
            "hit_rate": hits / samples if samples else None, "details": details}
