"""Tests for scripts/fetch_tdx_sector_klines.py.

脚本不在包内，importlib 加载（同 test_evaluate_agent_vs_up.py 模式）。
2026-08-27 修复两个 bug：
1. --only 全部已最新（0 待拉）时 main() 返回 1 → cron/watcher 视为失败；
   幂等无事可做应返回 0。
2. `os._exit(code)` 前未 flush stdout → 管道场景下输出全空（静默失败假象）。
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
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


class TestLoadTargetCodes:
    def test_only_codes_respected(self, mod, env):
        """--only 指定代码时只拉指定集合，忽略 sector_json。"""
        sector_json, db_path = env
        todo = mod._load_target_codes(
            sector_json, db_path, only_codes=["600036"])
        assert todo == ["600036"]

    def test_fresh_codes_skipped(self, mod, env):
        """已有最近数据（动态阈值内）的代码跳过（断点续拉）。"""
        from datetime import date, timedelta
        sector_json, db_path = env
        fresh_date = (date.today() - timedelta(days=3)).isoformat()
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO stocks_kline VALUES ('600036', ?)", (fresh_date,))
        conn.commit()
        conn.close()
        todo = mod._load_target_codes(
            sector_json, db_path, only_codes=["600036", "601398"])
        assert todo == ["601398"]

    def test_all_fresh_returns_empty(self, mod, env):
        """全部已最新 → todo 空（配合 main 返回 0 修复 bug1）。"""
        from datetime import date, timedelta
        sector_json, db_path = env
        fresh_date = (date.today() - timedelta(days=3)).isoformat()
        conn = sqlite3.connect(str(db_path))
        for c in ("600036", "601398"):
            conn.execute("INSERT INTO stocks_kline VALUES (?, ?)", (c, fresh_date))
        conn.commit()
        conn.close()
        todo = mod._load_target_codes(
            sector_json, db_path, only_codes=["600036", "601398"])
        assert todo == []

    def test_stale_data_not_skipped(self, mod, env):
        """bug4 回归：最新数据早于动态阈值（10天前）必须重拉，不得用硬编码日期误判。

        2026-08-27 前实现硬编码 "2026-08-01"，8 月过后 8-13 停更的
        4582 只被永久误判为已最新。
        """
        from datetime import date, timedelta
        sector_json, db_path = env
        stale_date = (date.today() - timedelta(days=30)).isoformat()
        conn = sqlite3.connect(str(db_path))
        for c in ("600036", "601398"):
            conn.execute("INSERT INTO stocks_kline VALUES (?, ?)", (c, stale_date))
        conn.commit()
        conn.close()
        todo = mod._load_target_codes(
            sector_json, db_path, only_codes=["600036", "601398"])
        assert sorted(todo) == ["600036", "601398"]


class TestMainReturnSemantics:
    def test_main_returns_zero_when_nothing_to_do(self, mod, env, monkeypatch):
        """bug1 回归：0 待拉（无事可做）时 main 必须返回 0，而非 1。"""
        sector_json, db_path = env
        conn = sqlite3.connect(str(db_path))
        from datetime import date, timedelta
        fresh_date = (date.today() - timedelta(days=3)).isoformat()
        for c in ("600036", "601398"):
            conn.execute("INSERT INTO stocks_kline VALUES (?, ?)", (c, fresh_date))
        conn.commit()
        conn.close()

        class FakeMkt:
            def get_kline(self, *a, **kw):  # pragma: no cover - 不应被调用
                raise AssertionError("无待拉代码时不应触碰 TDX")

        monkeypatch.setattr(mod, "TdxMarket", FakeMkt)
        rc = mod.main([
            "--only", "600036", "601398",
            "--sector-json", str(sector_json),
            "--db", str(db_path),
        ])
        assert rc == 0

    def test_main_returns_zero_on_success(self, mod, env, monkeypatch):
        """正常拉取成功返回 0。"""
        sector_json, db_path = env
        saved = []

        class FakeMkt:
            def get_kline(self, code, **kw):
                return [{"date": "2026-08-27", "close": 1.0}]

        monkeypatch.setattr(mod, "TdxMarket", FakeMkt)
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

        class FakeMkt:
            def get_kline(self, code, **kw):
                return None  # 重试后仍空

        monkeypatch.setattr(mod, "TdxMarket", FakeMkt)
        rc = mod.main([
            "--only", "600036",
            "--sector-json", str(sector_json),
            "--db", str(db_path),
        ])
        assert rc == 1
