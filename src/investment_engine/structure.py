"""通用顶底结构识别：MACD 背离 + 金叉/死叉结构形成。

输入 K 线（含 close/low/high，按时间升序），自算 MACD（EMA12/26/9，口径对齐
`scripts/update_index_klines_intraday.py::_ema`），识别顶/底背离与结构形成。

通用性：不绑定指数/ETF/个股，任何「带 OHLC 的 K 线序列」都能算。
- 底背离：价格创阶段新低，但 DIF 未同步创新低（抬高）→ 下跌动能衰竭。
- 顶背离：价格创阶段新高，但 DIF 未同步创新高（降低）→ 上涨动能衰竭。
- 结构形成：背离后 DIF 金叉 DEA（底部）/ 死叉（顶部）→ 背离被确认。

对应 UP 方法论（framework/market_analysis_framework.txt）：
  价格创新低 + DIF未同步新低 → 底背离（钝化中）→ 观察
  底背离后 DIF上穿DEA（金叉）→ 底部结构形成 → 可试错
"""
from __future__ import annotations


def _ema(values: list[float], period: int) -> list[float | None]:
    """标准 EMA。前 period-1 根 None，第 period 根 SMA 种子，之后递推。"""
    if len(values) < period:
        return [None] * len(values)
    k = 2.0 / (period + 1)
    result: list[float | None] = [None] * (period - 1)
    result.append(sum(values[:period]) / period)
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))  # type: ignore[operator]
    return result


def compute_macd(closes: list[float]) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """计算 MACD。返回 (dif, dea, macd_hist)，各长度 n，前 25 根 dif 为 None。"""
    n = len(closes)
    e12 = _ema(closes, 12)
    e26 = _ema(closes, 26)
    dif: list[float | None] = [None] * n
    for i in range(n):
        a, b = e12[i], e26[i]
        if a is not None and b is not None:
            dif[i] = a - b
    valid = [d for d in dif if d is not None]
    if not valid:
        return dif, [None] * n, [None] * n
    start = next(i for i, d in enumerate(dif) if d is not None)
    dea_raw = _ema(valid, 9)
    dea: list[float | None] = [None] * n
    for i, v in enumerate(dea_raw):
        if v is not None:
            dea[start + i] = v
    hist: list[float | None] = [None] * n
    for i in range(n):
        a, b = dif[i], dea[i]
        if a is not None and b is not None:
            hist[i] = (a - b) * 2
    return dif, dea, hist


def _find_pivots(klines: list[dict], window: int = 5) -> list[dict]:
    """局部极值点。返回 [{idx, type(bottom|top), price, dif, time}]，按 idx 升序。"""
    pivots: list[dict] = []
    n = len(klines)
    for i in range(window, n - window):
        if klines[i].get("dif") is None:  # MACD 未算出的头部，无法做背离判断
            continue
        seg = klines[i - window:i + window + 1]
        if klines[i]["low"] == min(k["low"] for k in seg):
            pivots.append({"idx": i, "type": "bottom", "price": klines[i]["low"],
                           "dif": klines[i].get("dif"), "time": klines[i].get("bar_time")})
        if klines[i]["high"] == max(k["high"] for k in seg):
            pivots.append({"idx": i, "type": "top", "price": klines[i]["high"],
                           "dif": klines[i].get("dif"), "time": klines[i].get("bar_time")})
    return pivots


def _find_cross(klines: list[dict], after_idx: int, direction: str) -> dict | None:
    """找 after_idx（含）之后最近一次 DIF 穿越 DEA。

    direction: 'golden'（金叉，dif 上穿 dea）/ 'dead'（死叉，dif 下穿 dea）。
    返回 {idx, time} 或 None。
    """
    for i in range(after_idx, len(klines) - 1):
        d, d1 = klines[i].get("dif"), klines[i + 1].get("dif")
        e, e1 = klines[i].get("dea"), klines[i + 1].get("dea")
        if d is None or d1 is None or e is None or e1 is None:
            continue
        if direction == "golden" and d <= e and d1 > e1:
            return {"idx": i + 1, "time": klines[i + 1].get("bar_time")}
        if direction == "dead" and d >= e and d1 < e1:
            return {"idx": i + 1, "time": klines[i + 1].get("bar_time")}
    return None


def _invalidated(klines: list[dict], pivots: list[dict], kind: str) -> dict | None:
    """检测「钝化消失」（invalidated）：更早一对未确认背离被新极值抹除。

    语义（UP 2026-08-18 盘中：「若下午涨速转快，60分钟顶部钝化则会自然消失」）：
    - p1→p2 曾背离（价新高 + DIF 更低），但 p2 之后未出现死叉/金叉确认；
    - p3 价再创极值且 DIF 不再更低（涨速转快、动能追上）→ 原钝化消失。
    注意：p2→p3 之间若有交叉，背离已确认（formed），不算消失；
    p3 之后的交叉是新一轮结构，与本判断无关。
    """
    pts = [p for p in pivots if p["type"] == kind]
    if len(pts) < 3:
        return None
    p1, p2, p3 = pts[-3], pts[-2], pts[-1]
    if kind == "top":
        diverged = p2["price"] > p1["price"] and p2["dif"] < p1["dif"]
        erased = p3["price"] > p2["price"] and p3["dif"] >= p2["dif"]
        cross_dir = "dead"
    else:
        diverged = p2["price"] < p1["price"] and p2["dif"] > p1["dif"]
        erased = p3["price"] < p2["price"] and p3["dif"] <= p2["dif"]
        cross_dir = "golden"
    if not diverged or not erased:
        return None
    if _find_cross(klines[p2["idx"]:p3["idx"] + 1], 0, cross_dir):
        return None
    return {"state": "invalidated", "time": p3["time"], "theoretical_days": None}


def _find_recent_formed(
    klines: list[dict], pivots: list[dict], kind: str, days: tuple | None,
) -> dict | None:
    """找最近一次「结构形成」事件（背离 + 随后金叉/死叉确认），而非当前状态。

    用途：即使当前已不在背离状态（如反弹已走了一段），也能定位最近一次
    底部/顶部结构形成的时间 —— 这是「反弹第几天」的起点锚。
    """
    pts = [p for p in pivots if p["type"] == kind]
    cross_dir = "golden" if kind == "bottom" else "dead"
    formed: dict | None = None
    for i in range(len(pts) - 1):
        p1, p2 = pts[i], pts[i + 1]
        if kind == "bottom":
            diverged = p2["price"] < p1["price"] and p2["dif"] > p1["dif"]
        else:
            diverged = p2["price"] > p1["price"] and p2["dif"] < p1["dif"]
        if not diverged:
            continue
        cross = _find_cross(klines, p2["idx"], cross_dir)
        if cross:
            formed = {"time": cross["time"],
                      "theoretical_days": days if days != (None, None) else None}
    return formed


# 级别 → 理论天数映射（反弹/调整窗口）。来源：UP claims + framework 对照表。
# 值：(min_days, max_days)；None 表示该方向无明确天数锚点。
LEVEL_DAYS: dict[str, dict[str, tuple[int | None, int | None]]] = {
    "30min":  {"bottom": (3, 3),   "top": (None, None)},   # 30min底=3天反弹
    "60min":  {"bottom": (2, 2),   "top": (3, 3)},          # 60min底=2天（单级别）；60min顶=3天调整（UP 2026-08-18 早盘：「60分钟顶部钝化如果形成对应调整时间是3天」）
    "90min":  {"bottom": (6, 8),   "top": (8, 8)},          # 90min顶=8天调整；60/90共振=6-8天
    "120min": {"bottom": (12, 12), "top": (4, 6)},          # 120min底=12天；双顶=4-6天
    "daily":  {"bottom": (None, None), "top": (None, None)},
}


def td_sequential(closes: list[float]) -> dict:
    """神奇九转（TD 序列）计数：当前连续上涨/下跌结构计数。

    上涨结构：close[i] > close[i-4] 连续计数，中断归零，达 9 即「高9」；
    下跌结构：close[i] < close[i-4] 连续计数，中断归零，达 9 即「低9」。
    （UP 2026-08-18 盘中：「若下午继续走弱，60分钟高9就不成立」——计数被
    反向K线打断则不成立，与本实现的中断归零一致。）

    返回 {"direction": "up"|"down"|None, "count": int, "completed": bool}。
    """
    up = down = 0
    for i in range(4, len(closes)):
        up = up + 1 if closes[i] > closes[i - 4] else 0
        down = down + 1 if closes[i] < closes[i - 4] else 0
    if up:
        return {"direction": "up", "count": up, "completed": up >= 9}
    if down:
        return {"direction": "down", "count": down, "completed": down >= 9}
    return {"direction": None, "count": 0, "completed": False}


def detect_structure(
    klines: list[dict],
    window: int = 5,
    timeframe: str | None = None,
) -> dict:
    """识别单级别顶底结构。

    Args:
        klines: K 线序列（升序），每根含 close/low/high（bar_time 可选）。
                若已含 dif/dea 则复用，否则自算 MACD。
        window: 极值点识别窗口（前后各 window 根）。
        timeframe: 级别（'30min'/'60min'/'90min'/'120min'/'daily'），用于查理论天数。

    Returns:
        {
          "bottom": {"state": "formed|divergence|invalidated", "time": str,
                     "theoretical_days": (min,max)|None} | None,
          "top":    {...} | None,
          "td9":    {"direction": "up|down|None", "count": int, "completed": bool},
        }
        某方向无结构时对应键为 None；invalidated = 未确认背离被新极值抹除（钝化消失）。
    """
    closes = [k["close"] for k in klines]
    dif, dea, _hist = compute_macd(closes)
    for i, k in enumerate(klines):
        if "dif" not in k or k.get("dif") is None:
            k["dif"] = dif[i]
        if "dea" not in k or k.get("dea") is None:
            k["dea"] = dea[i]

    pivots = _find_pivots(klines, window)
    bottoms = [p for p in pivots if p["type"] == "bottom"]
    tops = [p for p in pivots if p["type"] == "top"]

    days = LEVEL_DAYS.get(timeframe or "", {})

    def _assess(pair_prev: dict, pair_last: dict, kind: str) -> dict | None:
        """kind: 'bottom'（底背离）/ 'top'（顶背离）。"""
        if kind == "bottom":
            diverged = pair_last["price"] < pair_prev["price"] and pair_last["dif"] > pair_prev["dif"]
            cross = _find_cross(klines, pair_last["idx"], "golden") if diverged else None
        else:
            diverged = pair_last["price"] > pair_prev["price"] and pair_last["dif"] < pair_prev["dif"]
            cross = _find_cross(klines, pair_last["idx"], "dead") if diverged else None
        if not diverged:
            return None
        state = "formed" if cross else "divergence"
        signal = cross or {"idx": pair_last["idx"], "time": pair_last["time"]}
        d = days.get(kind, (None, None))
        return {
            "state": state,
            "time": signal["time"],
            "theoretical_days": d if d != (None, None) else None,
        }

    result: dict = {"bottom": None, "top": None}
    if len(bottoms) >= 2:
        result["bottom"] = _assess(bottoms[-2], bottoms[-1], "bottom")
    if len(tops) >= 2:
        result["top"] = _assess(tops[-2], tops[-1], "top")
    # 生命周期补充：最新一对不背离时，检查更早的未确认背离是否已被抹除（钝化消失）
    if result["bottom"] is None:
        result["bottom"] = _invalidated(klines, pivots, "bottom")
    if result["top"] is None:
        result["top"] = _invalidated(klines, pivots, "top")
    # 最近结构形成历史（反弹/调整的起点锚，即使当前已不在背离状态）
    result["recent_bottom"] = _find_recent_formed(
        klines, pivots, "bottom", days.get("bottom", (None, None)))
    result["recent_top"] = _find_recent_formed(
        klines, pivots, "top", days.get("top", (None, None)))
    result["td9"] = td_sequential(closes)
    return result


def detect_multi_tf(
    tf_klines: dict[str, list[dict]],
    window: int = 5,
) -> dict[str, dict]:
    """多级别结构识别。输入 {timeframe: klines}，返回 {timeframe: detect_structure(...)}。"""
    return {tf: detect_structure(kl, window=window, timeframe=tf) for tf, kl in tf_klines.items()}
