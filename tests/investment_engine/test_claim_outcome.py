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

    def test_reason_starting_with_pipe_quoted(self, tmp_path):
        """回归：reason 以 | 开头（neutral_window 的 |x%| 文案）不得炸文件。"""
        p = tmp_path / "c.yaml"
        p.write_text("claims:\n- id: claim-a\n  confidence: high\n", encoding="utf-8")
        write_outcome_to_yaml(p, "claim-a", {"result": "neutral_window",
                                             "reason": "|-0.81%| < 1.0% 阈值"})
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert data["claims"][0]["outcome"]["reason"] == "|-0.81%| < 1.0% 阈值"

    def test_rationale_starting_with_indicator_quoted(self, tmp_path):
        p = tmp_path / "c.yaml"
        from investment_engine.claim_outcome import write_block_to_yaml
        p.write_text("claims:\n- id: claim-a\n", encoding="utf-8")
        write_block_to_yaml(p, "claim-a", "direction",
                            {"value": "neutral", "rationale": "- 非方向判断"})
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert data["claims"][0]["direction"]["rationale"] == "- 非方向判断"

    def test_missing_claim_raises(self, tmp_path):
        p = tmp_path / "c.yaml"
        p.write_text("claims:\n- id: claim-a\n", encoding="utf-8")
        with pytest.raises(LookupError):
            write_outcome_to_yaml(p, "claim-nope", {"result": "hit"})

    def test_dict_format_with_top_level_list(self, tmp_path):
        """回归：单 claim 字典格式且含顶层列表值（related_stocks），
        块必须到 EOF，不得把列表项当块尾（claim-20260904-015 实录）。"""
        p = tmp_path / "c.yaml"
        p.write_text(
            "id: claim-dict\n"
            "topic: 液冷主线\n"
            "related_stocks:\n"
            "- code: '688668'\n"
            "  name: 鼎通科技\n"
            "tags:\n"
            "- 液冷\n",
            encoding="utf-8",
        )
        write_outcome_to_yaml(p, "claim-dict", {"result": "hit", "basis_code": "sh000300"})
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert data["outcome"]["result"] == "hit"
        assert data["related_stocks"] == [{"code": "688668", "name": "鼎通科技"}]
        assert data["tags"] == ["液冷"]

    def test_mid_block_id_and_quoted(self, tmp_path):
        """存量非常规写法：id 不在块首、带引号（claim-20261011-001 实录）。"""
        p = tmp_path / "c.yaml"
        p.write_text(
            "claims:\n"
            "- source_path: x.md\n"
            "  source_date: '2026-10-11'\n"
            "  confidence: high\n"
            "  id: 'claim-x-mid'\n"
            "  statement: s\n",
            encoding="utf-8",
        )
        write_outcome_to_yaml(p, "claim-x-mid", {"result": "hit"})
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert data["claims"][0]["outcome"]["result"] == "hit"
        assert data["claims"][0]["confidence"] == "high"

    def test_id_with_trailing_comment(self, tmp_path):
        p = tmp_path / "c.yaml"
        p.write_text("claims:\n- id: claim-a   # 早盘\n  confidence: high\n",
                     encoding="utf-8")
        write_outcome_to_yaml(p, "claim-a", {"result": "miss"})
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert data["claims"][0]["outcome"]["result"] == "miss"

    def test_mid_block_id_with_nested_lists(self, tmp_path):
        """claim-20261011-001 实录结构：id 在块中间，supersedes 列表项与
        字段同层（2 空格），tags 块序列与 key 同层，不得误定位块首/块尾。"""
        p = tmp_path / "c.yaml"
        p.write_text(
            "claims:\n"
            "- source_path: x.md\n"
            "  source_date: '2026-10-11'\n"
            "  supersedes:\n"
            "  - claim-old-1\n"
            "  - claim-old-2\n"
            "  id: claim-mid\n"
            "  tags:\n"
            "  - 报复性反弹\n"
            "  - 趋势反转\n"
            "  school: qing\n"
            "- source_path: y.md\n"
            "  id: claim-second\n",
            encoding="utf-8",
        )
        write_outcome_to_yaml(p, "claim-mid", {"result": "hit", "basis_code": "sh000300"})
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        c0, c1 = data["claims"]
        assert c0["id"] == "claim-mid"
        assert c0["outcome"]["result"] == "hit"
        assert c0["supersedes"] == ["claim-old-1", "claim-old-2"]
        assert c0["tags"] == ["报复性反弹", "趋势反转"]
        assert c0["school"] == "qing"
        assert "outcome" not in c1
