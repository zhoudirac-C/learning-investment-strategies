"""Tests for claim_outcome：5 交易日 forward 结算 + outcome 块 YAML 回写。

口径（spec 2026-10-24-m3-outcome-writeback）：
- t0 = 首个 >= source_date 的交易日收盘；t5 = 其后第 5 个交易日收盘
- |fwd_return| ≥ 1.0% 计 hit/miss（方向一致=hit），以下 neutral_window
- t5 不存在 → pending_data；无 basis/K线 → insufficient_data
- 回写幂等：二次回写覆盖不残留旧键；原字段无损
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from investment_engine.claim_outcome import (  # noqa: E402
    HIT_THRESHOLD_PCT,
    WINDOW_DAYS,
    normalize_stock_code,
    settle_claim,
    write_outcome_to_yaml,
)

TRADING_DAYS = [
    ("2026-10-08", 100.0), ("2026-10-09", 101.0), ("2026-10-12", 102.0),
    ("2026-10-13", 103.0), ("2026-10-14", 104.0), ("2026-10-15", 105.0),
    ("2026-10-16", 106.0), ("2026-10-19", 107.0), ("2026-10-20", 108.0),
    ("2026-10-21", 109.0), ("2026-10-22", 110.0),
]


@pytest.fixture
def kline_db(tmp_path):
    db = tmp_path / "kline_cache.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE index_klines (code TEXT, timeframe TEXT, bar_time TEXT, close REAL)")
    con.execute("CREATE TABLE stocks_kline (code TEXT, trade_date TEXT, close REAL)")
    for d, c in TRADING_DAYS:
        con.execute("INSERT INTO index_klines VALUES ('sh000300','daily',?,?)", (d, c))
        con.execute("INSERT INTO stocks_kline VALUES ('000001.SZ',?,?)", (d, c * 0.5))
    con.commit()
    con.close()
    return db


def _claim(source_date: str, value: str = "bullish", basis: str = "sh000300") -> dict:
    return {
        "id": "claim-test-001",
        "source_date": source_date,
        "claim_type": "market-cycle",
        "direction": {"value": value, "basis_kind": "index", "basis_code": basis},
    }


class TestNormalizeCode:
    def test_main_board_sh(self):
        assert normalize_stock_code("600519") == "600519.SH"

    def test_star_market(self):
        assert normalize_stock_code("688981") == "688981.SH"

    def test_shenzhen_main(self):
        assert normalize_stock_code("000001") == "000001.SZ"

    def test_chinext(self):
        assert normalize_stock_code("300750") == "300750.SZ"

    def test_already_suffixed(self):
        assert normalize_stock_code("601318.SH") == "601318.SH"

    def test_index_untouched(self):
        assert normalize_stock_code("sh000300") == "sh000300"


class TestSettle:
    def test_bullish_hit(self, kline_db):
        # t0=10-15(105) → t5=10-22(110): +4.76%
        o = settle_claim(_claim("2026-10-15"), kline_db)
        assert o["result"] == "hit"
        assert o["t0_date"] == "2026-10-15" and o["t5_date"] == "2026-10-22"
        assert round(o["fwd_return_pct"], 2) == round((110 - 105) / 105 * 100, 2)

    def test_bullish_miss(self, kline_db):
        con = sqlite3.connect(kline_db)
        con.execute("UPDATE index_klines SET close=96.0 WHERE bar_time='2026-10-22'")  # -8.57%
        con.commit()
        assert settle_claim(_claim("2026-10-15"), kline_db)["result"] == "miss"

    def test_neutral_window_below_threshold(self, kline_db):
        con = sqlite3.connect(kline_db)
        con.execute("UPDATE index_klines SET close=105.8 WHERE bar_time='2026-10-22'")  # +0.76%
        con.commit()
        assert settle_claim(_claim("2026-10-15"), kline_db)["result"] == "neutral_window"

    def test_threshold_boundary_is_hit(self, kline_db):
        # +1.0% 整 = hit（阈值含等号）
        con = sqlite3.connect(kline_db)
        con.execute("UPDATE index_klines SET close=106.05 WHERE bar_time='2026-10-22'")
        con.commit()
        assert settle_claim(_claim("2026-10-15"), kline_db)["result"] == "hit"

    def test_bearish_symmetric(self, kline_db):
        assert settle_claim(_claim("2026-10-15", value="bearish"), kline_db)["result"] == "miss"

    def test_stock_basis(self, kline_db):
        c = _claim("2026-10-15", basis="000001")
        o = settle_claim(c, kline_db)
        assert o["basis_code"] == "000001.SZ"
        assert o["result"] == "hit"

    def test_t0_rolls_to_next_trading_day(self, kline_db):
        # 10-10 是周六 → t0=10-12(102) → t5=10-19(107): +4.90%（仍是第 5 日）
        o = settle_claim(_claim("2026-10-10"), kline_db)
        assert o["t0_date"] == "2026-10-12"
        assert o["result"] == "hit"

    def test_pending_when_t5_missing(self, kline_db):
        # 10-22 起算第 5 日（10-29）超出最后一根 10-22
        o = settle_claim(_claim("2026-10-22"), kline_db)
        assert o["result"] == "pending_data"

    def test_insufficient_unknown_basis(self, kline_db):
        o = settle_claim(_claim("2026-10-15", basis="sh999999"), kline_db)
        assert o["result"] == "insufficient_data"
        assert o["reason"]

    def test_insufficient_missing_basis(self, kline_db):
        c = _claim("2026-10-15", basis="")
        assert settle_claim(c, kline_db)["result"] == "insufficient_data"

    def test_neutral_direction_rejected(self, kline_db):
        with pytest.raises(ValueError):
            settle_claim(_claim("2026-10-15", value="neutral"), kline_db)


class TestWriteOutcome:
    def test_write_and_roundtrip(self, tmp_path):
        p = tmp_path / "c.yaml"
        p.write_text(
            "claims:\n"
            "- id: claim-a\n"
            "  subject: s\n"
            "  confidence: high\n"
            "- id: claim-b\n"
            "  subject: t\n",
            encoding="utf-8",
        )
        out = {"result": "hit", "fwd_return_pct": 1.23, "t0_date": "2026-10-15",
               "t5_date": "2026-10-21", "t0_close": 105.0, "t5_close": 106.3,
               "basis_code": "sh000300", "window_days": 5,
               "evaluated_at": "2026-10-24"}
        write_outcome_to_yaml(p, "claim-b", out)
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        claims = {c["id"]: c for c in data["claims"]}
        assert claims["claim-b"]["outcome"]["result"] == "hit"
        assert claims["claim-a"].get("outcome") is None
        assert claims["claim-b"]["subject"] == "t"

    def test_rewrite_overwrites_no_duplicates(self, tmp_path):
        p = tmp_path / "c.yaml"
        p.write_text("claims:\n- id: claim-a\n  confidence: high\n", encoding="utf-8")
        write_outcome_to_yaml(p, "claim-a", {"result": "miss", "reason": "x"})
        write_outcome_to_yaml(p, "claim-a", {"result": "hit", "reason": "y"})
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        oc = data["claims"][0]["outcome"]
        assert oc["result"] == "hit"
        text = p.read_text(encoding="utf-8")
        assert text.count("outcome:") == 1

    def test_missing_claim_raises(self, tmp_path):
        p = tmp_path / "c.yaml"
        p.write_text("claims:\n- id: claim-a\n", encoding="utf-8")
        with pytest.raises(LookupError):
            write_outcome_to_yaml(p, "claim-nope", {"result": "hit"})
