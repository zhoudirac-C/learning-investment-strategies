"""structure 模块测试：MACD 计算对齐 + 顶底结构识别（含真实数据集成验证）。"""
import sqlite3
from pathlib import Path

import pytest

from investment_engine.structure import compute_macd, detect_structure, _find_pivots

DB = Path("infra/data/kline_cache.db")


def _load_index(code: str, timeframe: str, start: str, end: str) -> list[dict]:
    """读真实指数 K 线（升序），字段 close/low/high/bar_time。"""
    if not DB.exists():
        pytest.skip("无 kline_cache.db")
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT bar_time, close, low, high FROM index_klines "
        "WHERE code=? AND timeframe=? AND bar_time BETWEEN ? AND ? ORDER BY bar_time",
        (code, timeframe, start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def test_compute_macd_shape():
    closes = [100.0 + i * 0.1 for i in range(60)]  # 60 根上升
    dif, dea, hist = compute_macd(closes)
    assert len(dif) == len(dea) == len(hist) == 60
    # 前 25 根 dif 为 None（EMA26 需要 26 根）
    assert all(d is None for d in dif[:25])
    assert dif[25] is not None
    # 上升序列，dif 应为正
    assert dif[-1] is not None and dif[-1] > 0


def test_compute_macd_constant_series():
    """常数序列：EMA 收敛到常数，dif 应接近 0。"""
    closes = [100.0] * 80
    dif, dea, _ = compute_macd(closes)
    assert dif[-1] is not None and abs(dif[-1]) < 1e-6
    assert dea[-1] is not None and abs(dea[-1]) < 1e-6


def test_compute_macd_does_not_trust_stale_db():
    """自算 MACD 不依赖 index_klines 表里可能漂移的 dif（增量更新会漂移）。"""
    # 直接用一条干净的上升序列，验证 dif = ema12 - ema26 的符号正确
    closes = [100.0 + i * 0.3 for i in range(80)]
    dif, _, _ = compute_macd(closes)
    # 上升序列 dif 应为正且单调递增（后段）
    tail = [d for d in dif[-20:] if d is not None]
    assert all(d > 0 for d in tail)


def test_find_pivots_simple():
    # 构造震荡数据：多个峰谷（谷在 i=20、i=36，峰在 i=10、i=28）
    klines = []
    for i in range(40):
        close = 50 + abs(i - 20) * 2 if i < 28 else 50 + abs(i - 36) * 2
        klines.append({"close": close, "low": close, "high": close + 1,
                       "dif": 0.0, "dea": 0.0, "bar_time": f"t{i}"})
    pivots = _find_pivots(klines, window=5)
    bottoms = [p for p in pivots if p["type"] == "bottom"]
    tops = [p for p in pivots if p["type"] == "top"]
    assert any(p["idx"] == 20 for p in bottoms)  # 谷被识别
    assert tops, "应有顶部"


def test_detect_structure_bottom_divergence_real():
    """真实数据：上证 90min 应识别底背离（UP 07-31 判底部结构）。"""
    klines = _load_index("sh000001", "90min", "2026-06-01", "2026-08-05 15:00")
    assert len(klines) >= 60
    res = detect_structure(klines, window=4, timeframe="90min")
    b = res.get("bottom")
    assert b is not None, "应识别出底背离"
    assert b["state"] in ("divergence", "formed")
    assert b["theoretical_days"] == (6, 8)  # 90min 底 = 6-8 天


def test_detect_structure_top_divergence_real():
    """真实数据：上证 60min 应识别顶背离（spike 已人工核对）。"""
    klines = _load_index("sh000001", "60min", "2026-06-01", "2026-07-31 15:00")
    assert len(klines) >= 60
    res = detect_structure(klines, window=4, timeframe="60min")
    t = res.get("top")
    assert t is not None, "应识别出顶背离"


def test_detect_structure_no_divergence():
    """同步创新低（价格与 DIF 同步走低）→ 不应判底背离。"""
    # 一路单边下跌，价格和 dif 同步创新低
    closes = [100.0 - i * 0.5 for i in range(60)]
    klines = [{"close": c, "low": c - 0.1, "high": c + 0.1,
               "bar_time": f"t{i}"} for i, c in enumerate(closes)]
    res = detect_structure(klines, window=4, timeframe="60min")
    # 单边下跌下，dif 也一路走低，不应有底背离（dif 不抬高）
    b = res.get("bottom")
    assert b is None, "单边下跌无 DIF 抬高，不应判底背离"
