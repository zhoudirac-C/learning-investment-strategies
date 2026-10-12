"""估值 overlay 覆盖范围测试（2026-10-12 用户拍板方案2）：

冰封区估值 overlay 从「仅最冷 TOP5」扩为「全部 cold 板块」——
否则新跨入冷区的板块（如 10-12 工业金属/电网设备）恰好在 TOP5 之外，
推送时看不到「便宜/冷但贵」判定，违背逆向机会的提醒初衷。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import board_sentiment_daily as m  # noqa: E402
from investment_engine.sentiment import valuation_overlay  # noqa: E402


def _cold_bars(n: int = 400) -> list[dict]:
    """构造必入 cold 区的K线：历史高量+近期地量阴跌（量能分位≈0，形态弱）。"""
    bars = []
    for i in range(n):
        amount = 1e9 if i < n - 5 else 1e6  # 近5日地量
        close = 100.0 * (1 - 0.0005 * i)    # 长期阴跌
        bars.append({"date": f"2026-01-{(i % 28) + 1:02d}", "close": close,
                     "amount": amount})
    return bars


def test_valuation_overlay_covers_all_cold_boards(tmp_path, monkeypatch):
    n_boards = 7  # > TOP5，TOP5 裁切必然漏掉 2 个
    klines = {f"测试板块{i}": _cold_bars() for i in range(n_boards)}

    monkeypatch.setattr(m, "load_board_klines", lambda: klines)
    monkeypatch.setattr(m, "load_billboard", lambda: {})
    monkeypatch.setattr(m, "get_stock_board_map", lambda: {})
    monkeypatch.setattr(m, "load_margin_by_board", lambda s2b: ({}, {}))
    monkeypatch.setattr(m, "OUT_DIR", tmp_path)

    called: list[str] = []

    def fake_assess(board: str, use_cache: bool = True) -> dict:
        called.append(board)
        return {"board": board, "method": "pe_percentile", "value": 50.0,
                "cheap": False}

    monkeypatch.setattr(valuation_overlay, "assess_valuation", fake_assess)
    monkeypatch.setattr(sys, "argv", ["board_sentiment_daily.py",
                                      "--date", "20261012"])

    assert m.main() == 0

    out = json.loads((tmp_path / "2026-10-12.json").read_text(encoding="utf-8"))
    cold = [b for b in out["boards"] if b["zone"] == "cold"]
    assert len(cold) == n_boards, f"构造的 {n_boards} 个板块应全部入 cold 区"
    # 核心断言：每个 cold 板块都算过估值，不只是 TOP5
    assert sorted(called) == sorted(b["name"] for b in cold), (
        f"估值调用 {sorted(called)} 未覆盖全部 cold 板块")
    for b in cold:
        assert b.get("valuation"), f"{b['name']} 缺 valuation"
        assert b.get("opportunity") is False
