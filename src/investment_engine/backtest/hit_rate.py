"""信号命中率统计：信号日收盘 → 第 horizon 个交易日收盘的收益与汇总。"""
from __future__ import annotations


def forward_return(klines: list[dict], signal_date: str, horizon: int) -> float | None:
    """信号日（含）之后第 horizon 个交易日收盘价 / 信号日收盘价 - 1。数据不足返回 None。"""
    dates = [k["date"] for k in klines]
    if signal_date not in dates:
        return None
    i = dates.index(signal_date)
    j = i + horizon
    if j >= len(klines):
        return None
    base = klines[i]["close"]
    if not base:
        return None
    return klines[j]["close"] / base - 1.0


def summarize(records: list[dict], horizons: tuple[int, ...] = (5, 10, 20)) -> dict:
    """records: [{"code", "date", "returns": {horizon: float | None}}]。

    返回 {horizon: {"samples", "hits", "hit_rate", "avg_return"}}；
    returns 为 None 的（数据不足）不计入该 horizon 样本。
    """
    stats: dict[int, dict] = {}
    for h in horizons:
        values = [r["returns"][h] for r in records if r.get("returns", {}).get(h) is not None]
        hits = sum(1 for v in values if v > 0)
        stats[h] = {
            "samples": len(values),
            "hits": hits,
            "hit_rate": hits / len(values) if values else None,
            "avg_return": sum(values) / len(values) if values else None,
        }
    return stats
