"""机械真值标签：用指数日 K 可计算特征给每个交易日贴市场阶段标签。

规则（spec 冻结版，按序匹配，先中先得）：
1. r20 ≤ -8% 或（r5 ≤ -4% 且 vol_trend ≥ 1.5）→ 恐慌
2. r20 ≤ -3% 或 pos20 ≤ 0.35 → 调整
3. r20 ≥ +4% 且 pos20 ≥ 0.6 → 主升
4. 其余 → 震荡
"""
from __future__ import annotations

STAGES = ("主升", "震荡", "调整", "恐慌")

_MIN_LOOKBACK = 24  # vol_trend 需要 i-24..i-5


def compute_features(klines: list[dict], i: int) -> dict | None:
    """klines 升序；计算第 i 日的特征。lookback 不足返回 None。"""
    if i < _MIN_LOOKBACK or i >= len(klines):
        return None
    close = klines[i]["close"]
    r20 = close / klines[i - 20]["close"] - 1.0
    r5 = close / klines[i - 5]["close"] - 1.0
    window = klines[i - 19 : i + 1]
    hi = max(k["high"] for k in window)
    lo = min(k["low"] for k in window)
    pos20 = (close - lo) / (hi - lo) if hi > lo else 0.5
    recent_vol = [k["volume"] or 0.0 for k in klines[i - 4 : i + 1]]
    prior_vol = [k["volume"] or 0.0 for k in klines[i - 24 : i - 4]]
    prior_mean = sum(prior_vol) / len(prior_vol)
    vol_trend = (sum(recent_vol) / len(recent_vol)) / prior_mean if prior_mean > 0 else None
    return {"r20": r20, "r5": r5, "pos20": pos20, "vol_trend": vol_trend}


def label_day(f: dict) -> str:
    if f["r20"] <= -0.08 or (f["r5"] <= -0.04 and f["vol_trend"] is not None and f["vol_trend"] >= 1.5):
        return "恐慌"
    if f["r20"] <= -0.03 or f["pos20"] <= 0.35:
        return "调整"
    if f["r20"] >= 0.04 and f["pos20"] >= 0.6:
        return "主升"
    return "震荡"


def label_series(klines: list[dict]) -> list[dict]:
    """全序列标注：[{"date", "label", "r20", "pos20", "r5", "vol_trend"}]，跳过 lookback 前缀。"""
    rows = []
    for i in range(len(klines)):
        f = compute_features(klines, i)
        if f is None:
            continue
        rows.append({"date": klines[i]["date"], "label": label_day(f), **f})
    return rows


def load_truth(db_path=None, index_code: str = "IDX000300") -> dict[str, str]:
    """从缓存读指数日 K，返回 {date: label}。"""
    from investment_engine.backtest.history import get_index_daily

    klines = get_index_daily(index_code, "2000-01-01", "2999-12-31", db_path=db_path)
    return {r["date"]: r["label"] for r in label_series(klines)}
