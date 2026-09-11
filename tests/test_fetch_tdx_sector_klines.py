"""Tests for scripts/fetch_tdx_sector_klines.py.

脚本不在包内，importlib 加载（同 test_evaluate_agent_vs_up.py 模式）。
2026-08-27 修复两个 bug：
1. --only 全部已最新（0 待拉）时 main() 返回 1 → cron/watcher 视为失败；
   幂等无事可做应返回 0。
2. `os._exit(code)` 前未 flush stdout → 管道场景下输出全空（静默失败假象）。

2026-09-11 数据源迁移：TdxMarket 直连 → marketdata.router 统一层
（腾讯 → 东财，显式排除 TDX）。测试改 patch 统一层 get_kline，
并新增：bar→行 字段映射、软时限收尾、连续失败中止、MarketDataError
单只失败不拖垮批次。
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "fetch_tdx_sector_klines.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("fetch_tdx_sector_klines", SCRIPT_PATH)
    m = importlib.util.module_from_spec(spec)
    sys.modules["fetch_tdx_sector_klines"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def env(tmp_path):
    """最小 sector_members.json + 空 kline db。"""
    sector_json = tmp_path / "sector_members.json"
    sector_json.write_text(json.dumps({
        "_built_at": 0, "_source": "test",
        "concept": {"5G概念": ["600036", "601398"]},
    }), encoding="utf-8")
    db_path = tmp_path / "kline_cache.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE stocks_kline (code TEXT, trade_date TEXT)")
    conn.commit()
    conn.close()
    return sector_json, db_path


def _bars(n: int = 3, base: float = 10.0) -> list[dict]:
    """统一层统一 shape 的 mock bars（bar_time 升序）。"""
    d0 = date(2026, 9, 1)
    return [
        {
            "bar_time": (d0 + timedelta(days=i)).isoformat(),
            "open": base + i, "high": base + i + 0.5, "low": base + i - 0.5,
            "close": base + i, "volume": 1000.0 * (i + 1), "amount": 0.0,
        }
        for i in range(n)
    ]


class TestLoadTargetCodes:
    def test_only_codes_respected(self, mod, env):
        """--only 指定代码时只拉指定集合，忽略 sector_json。"""
        sector_json, db_path = env
        todo = mod._load_target_codes(sector_json, db_path, only_codes=["600036"])
        assert todo == ["600036"]

    def test_fresh_codes_skipped(self, mod, env):
        """已有最近数据（动态阈值内）的代码跳过（断点续拉）。"""
        sector_json, db_path = env
        fresh_date = (date.today() - timedelta(days=3)).isoformat()
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO stocks_kline VALUES ('600036', ?)", (fresh_date,))
        conn.commit()
        conn.close()
        todo = mod._load_target_codes(sector_json, db_path,
                                      only_codes=["600036", "601398"])
        assert todo == ["601398"]

    def test_all_fresh_returns_empty(self, mod, env):
        """全部已最新 → todo 空（配合 main 返回 0 修复 bug1）。"""
        sector_json, db_path = env
        fresh_date = (date.today() - timedelta(days=3)).isoformat()
        conn = sqlite3.connect(str(db_path))
        for c in ("600036", "601398"):
            conn.execute("INSERT INTO stocks_kline VALUES (?, ?)", (c, fresh_date))
        conn.commit()
        conn.close()
        todo = mod._load_target_codes(sector_json, db_path,
                                      only_codes=["600036", "601398"])
        assert todo == []

    def test_stale_data_not_skipped(self, mod, env):
        """bug4 回归：最新数据早于动态阈值（10天前）必须重拉，不得用硬编码日期误判。

        2026-08-27 前实现硬编码 "2026-08-01"，8 月过后 8-13 停更的
        4582 只被永久误判为已最新。
        """
        sector_json, db_path = env
        stale_date = (date.today() - timedelta(days=30)).isoformat()
        conn = sqlite3.connect(str(db_path))
        for c in ("600036", "601398"):
            conn.execute("INSERT INTO stocks_kline VALUES (?, ?)", (c, stale_date))
        conn.commit()
        conn.close()
        todo = mod._load_target_codes(sector_json, db_path,
                                      only_codes=["600036", "601398"])
        assert sorted(todo) == ["600036", "601398"]


class TestRowsFromBars:
    """统一层 bar（bar_time）→ stocks_kline 行（date）字段映射。"""

    def test_shape_mapping_and_pct_change(self, mod):
        bars = _bars(3, base=10.0)
        rows = mod._rows_from_bars(bars)
        assert [r["date"] for r in rows] == ["2026-09-01", "2026-09-02", "2026-09-03"]
        assert rows[0]["close"] == 10.0
        assert rows[2]["close"] == 12.0
        # pct_change 首根 NULL（窗口内无前收盘），后续自算
        assert rows[0]["pct_change"] is None
        assert rows[1]["pct_change"] == pytest.approx(10.0, abs=1e-3)  # 10→11
        assert rows[2]["pct_change"] == pytest.approx((12 / 11 - 1) * 100, abs=1e-3)
        # turnover/amplitude 不映射（统一层不提供，历史口径即为 NULL）

    def test_missing_bar_time_falls_back(self, mod):
        b = _bars(1)
        b[0].pop("bar_time")
        b[0]["date"] = "2026-09-01"
        rows = mod._rows_from_bars(b)
        assert rows[0]["date"] == "2026-09-01"

    def test_empty_input(self, mod):
        assert mod._rows_from_bars([]) == []


class TestMainSemantics:
    def test_main_returns_zero_when_nothing_to_do(self, mod, env, monkeypatch):
        """bug1 回归：0 待拉（无事可做）时 main 必须返回 0，而非 1。"""
        sector_json, db_path = env
        fresh_date = (date.today() - timedelta(days=3)).isoformat()
        conn = sqlite3.connect(str(db_path))
        for c in ("600036", "601398"):
            conn.execute("INSERT INTO stocks_kline VALUES (?, ?)", (c, fresh_date))
        conn.commit()
        conn.close()

        def _boom(*a, **kw):  # pragma: no cover - 不应被调用
            raise AssertionError("无待拉代码时不应触碰数据源")

        monkeypatch.setattr(mod, "get_kline", _boom)
        rc = mod.main([
            "--only", "600036", "601398",
            "--sector-json", str(sector_json),
            "--db", str(db_path),
        ])
        assert rc == 0

    def test_main_returns_zero_on_success(self, mod, env, monkeypatch):
        """正常拉取成功返回 0（patch 统一层 get_kline）。"""
        sector_json, db_path = env
        saved: list = []

        def fake_get_kline(code, klt, count, *, sources=None):
            assert klt == 101 and count == mod.DAYS
            assert sources == mod.SOURCES  # 迁移后必须显式排除 TDX
            return _bars(3), "tencent"

        monkeypatch.setattr(mod, "get_kline", fake_get_kline)
        monkeypatch.setattr(mod, "save_klines",
                            lambda code, klines, db_path=None: saved.append(code))
        rc = mod.main([
            "--only", "600036",
            "--sector-json", str(sector_json),
            "--db", str(db_path),
        ])
        assert rc == 0
        assert saved == ["600036"]

    def test_main_returns_one_on_total_failure(self, mod, env, monkeypatch):
        """有目标但全部失败时仍返回 1（真实失败要暴露）。"""
        sector_json, db_path = env
        monkeypatch.setattr(mod.time, "sleep", lambda s: None)

        def fake_get_kline(code, klt, count, *, sources=None):
            return [], "tencent"  # 全链空

        monkeypatch.setattr(mod, "get_kline", fake_get_kline)
        rc = mod.main([
            "--only", "600036",
            "--sector-json", str(sector_json),
            "--db", str(db_path),
        ])
        assert rc == 1

    def test_marketdata_error_isolated_per_code(self, mod, env, monkeypatch):
        """MarketDataError 只计单只失败，不拖垮批次。"""
        sector_json, db_path = env
        saved: list = []
        monkeypatch.setattr(mod.time, "sleep", lambda s: None)

        def fake_get_kline(code, klt, count, *, sources=None):
            if code == "600036":
                raise mod.MarketDataError("全链失败：腾讯超时, 东财超时")
            return _bars(2), "tencent"

        monkeypatch.setattr(mod, "get_kline", fake_get_kline)
        monkeypatch.setattr(mod, "save_klines",
                            lambda code, klines, db_path=None: saved.append(code))
        rc = mod.main([
            "--only", "600036", "601398",
            "--sector-json", str(sector_json),
            "--db", str(db_path),
        ])
        assert rc == 0  # 601398 成功 → 本轮有效
        assert saved == ["601398"]

    def test_consecutive_failures_abort(self, mod, env, monkeypatch):
        """连续 ≥20 只全链失败 → 判定网络级故障中止（不逐只空转）。"""
        sector_json, db_path = env
        codes = [f"{600000 + i:06d}" for i in range(25)]
        sector_json.write_text(json.dumps({
            "_built_at": 0, "_source": "test",
            "concept": {"测试板块": codes},
        }), encoding="utf-8")
        monkeypatch.setattr(mod.time, "sleep", lambda s: None)

        def fake_get_kline(code, klt, count, *, sources=None):
            raise mod.MarketDataError("全链失败")

        monkeypatch.setattr(mod, "get_kline", fake_get_kline)
        rc = mod.main([
            "--only", *codes,
            "--sector-json", str(sector_json),
            "--db", str(db_path),
        ])
        assert rc == 1

    def test_soft_deadline_stops_batch(self, mod, env, monkeypatch):
        """软时限到达 → 安全收尾返回 0（有成功即有效），剩余下轮续拉。"""
        sector_json, db_path = env
        codes = [f"{600000 + i:06d}" for i in range(30)]
        sector_json.write_text(json.dumps({
            "_built_at": 0, "_source": "test",
            "concept": {"测试板块": codes},
        }), encoding="utf-8")

        saved: list = []

        class FakeTime:
            """可控时钟：sleep 推进时钟，软时限按虚拟时间判定（确定性）。"""

            def __init__(self):
                self.t = 1000.0

            def time(self):
                return self.t

            def sleep(self, s):
                self.t += s

        monkeypatch.setattr(mod, "time", FakeTime())
        monkeypatch.setattr(mod, "SOFT_DEADLINE_S", 1.0)

        def fake_get_kline(code, klt, count, *, sources=None):
            return _bars(2), "tencent"

        monkeypatch.setattr(mod, "get_kline", fake_get_kline)
        monkeypatch.setattr(mod, "save_klines",
                            lambda code, klines, db_path=None: saved.append(code))
        rc = mod.main([
            "--only", *codes,
            "--sector-json", str(sector_json),
            "--db", str(db_path),
        ])
        assert rc == 0
        assert 0 < len(saved) < 30  # 只跑了一部分就收尾
