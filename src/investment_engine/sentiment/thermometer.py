"""板块情绪温度计核心（纯函数，无 IO）。

温度 = 0.40×量能分位 + 0.25×龙虎榜散户化 + 0.20×融资热度 + 0.15×量价形态。
可选分量缺失时，权重在可用分量间按比例重归一化。

设计原则（2026-10-11 用户拍板）：反向指标——高分=人声鼎沸（卖给散户区），
低分=无人问津（配合估值 overlay 找逆向建仓区）。
"""
from __future__ import annotations

WEIGHTS = {"volume": 0.40, "billboard": 0.25, "margin": 0.20, "pattern": 0.15}
HOT, COLD = 80.0, 20.0


def percentile_rank(values: list[float], current: float) -> float:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 50.0
    # 极值钳制：本指标专为极端检测服务，创新高=100、创新低=0
    if current >= vals[-1]:
        return 100.0
    if current <= vals[0]:
        return 0.0
    below = sum(1 for v in vals if v < current)
    return round(100.0 * below / len(vals), 1)


def _ma5_amounts(bars: list[dict]) -> list[float]:
    amts = [b["amount"] for b in bars]
    return [sum(amts[i - 4:i + 1]) / 5 for i in range(4, len(amts))]


def volume_component(bars: list[dict], window: int = 250) -> float:
    """量能分位：当前 5 日均额 在过去 window 日 5 日均额序列中的分位。"""
    ma5 = _ma5_amounts(bars)[-window:]
    if len(ma5) < 20:
        return 50.0
    return percentile_rank(ma5[:-1], ma5[-1])


def pattern_component(bars: list[dict]) -> float:
    """量价形态：涨+放量=热；天量滞涨(出货特征)=更热；跌+缩量=冷。"""
    if len(bars) < 25:
        return 50.0
    closes = [b["close"] for b in bars]
    amts = [b["amount"] for b in bars]
    ret20 = (closes[-1] / closes[-21] - 1) * 100
    amt_ratio = (sum(amts[-5:]) / 5) / max(sum(amts[-25:-5]) / 20, 1e-9)
    score = 50.0 + ret20 * 2.0  # 20日涨幅每 +1% → +2 分
    score += min(max((amt_ratio - 1) * 40, -25), 25)  # 放量±
    # 天量滞涨：5 日均额 > 25 日均额 1.8 倍 且近 5 日涨幅 <1% → 出货特征，直接热
    if amt_ratio > 1.8 and abs((closes[-1] / closes[-6] - 1) * 100) < 1.0:
        score = max(score, 85.0)
    return round(max(0.0, min(100.0, score)), 1)


def billboard_component(board_stats: dict | None) -> float | None:
    """board_stats: {"retail_buy_ratio": 0-1, "board_hits_20d": int}"""
    if not board_stats:
        return None
    ratio = board_stats.get("retail_buy_ratio", 0.0)
    hits = board_stats.get("board_hits_20d", 0)
    return round(min(100.0, ratio * 70 + min(hits, 15) / 15 * 30), 1)


def margin_component(margin_chg_20d: float | None, hist: list[float]) -> float | None:
    if margin_chg_20d is None or len(hist) < 60:
        return None
    return percentile_rank(hist, margin_chg_20d)


def compute_temperature(bars: list[dict], board_stats: dict | None = None,
                        margin_chg: float | None = None,
                        margin_hist: list[float] | None = None) -> dict:
    comps: dict[str, float | None] = {
        "volume": volume_component(bars),
        "pattern": pattern_component(bars),
        "billboard": billboard_component(board_stats),
        "margin": margin_component(margin_chg, margin_hist or []),
    }
    avail = {k: v for k, v in comps.items() if v is not None}
    wsum = sum(WEIGHTS[k] for k in avail)
    score = sum(avail[k] * WEIGHTS[k] for k in avail) / wsum if wsum else 50.0
    score = round(score, 1)
    zone = "hot" if score >= HOT else ("cold" if score <= COLD else "neutral")
    return {"score": score, "components": comps, "zone": zone,
            "as_of": bars[-1]["date"] if bars else None}
