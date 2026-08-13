"""update_index_klines_intraday 的 daily 覆盖 bug 回归测试。

bug：daily 级别 bar_time 只到日期（'2026-08-12'），早盘写入盘中快照后，
收盘价因 `db_latest >= newest_bar` 判定被跳过，收盘价永远覆盖不了早盘快照。
修复后：同 bar_time 但 close 变化的 bar 应被覆盖更新（重算 MACD）。
"""
import sqlite3
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import update_index_klines_intraday as mod  # noqa: E402


def _bars(rows):
    """构造 fetch_latest_klines 返回的 bar 列表（升序）。"""
    return [
        {"bar_time": bt, "open": o, "close": c, "high": h, "low": l,
         "volume": 100.0, "amount": 0.0}
        for bt, o, c, h, l in rows
    ]


def _init_db(db: Path, code: str, timeframe: str, rows) -> None:
    """往 index_klines 表写入初始 bar（模拟早盘快照）。"""
    conn = sqlite3.connect(str(db))
    conn.executemany(
        """INSERT OR REPLACE INTO index_klines
           (code, timeframe, bar_time, open, high, low, close, volume, amount,
            dif, dea, macd_hist, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (code, timeframe, r["bar_time"], r["open"], r["high"], r["low"],
             r["close"], r["volume"], r["amount"], None, None, None, "2026-08-12T09:52:00")
            for r in rows
        ],
    )
    conn.commit()
    conn.close()


def _read_close(db: Path, code: str, timeframe: str, bar_time: str) -> float | None:
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT close FROM index_klines WHERE code=? AND timeframe=? AND bar_time=?",
        (code, timeframe, bar_time),
    ).fetchone()
    conn.close()
    return row[0] if row else None


class TestDailyBarCloseOverride:
    """daily 级别：同 bar_time 但 close 变化 → 覆盖更新。"""

    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_idx_update_{id(self)}.db"
        if self.db.exists():
            self.db.unlink()
        # 建 index_klines 表结构（复用 kline_cache.init_db）
        from qing_investment.kline_cache import init_db
        init_db(db_path=self.db)
        # 写 30 根历史 daily（收盘价固定），供 MACD 重算有足够窗口
        hist = [("2026-07-%02d" % (i + 1), 3900.0 + i, 3900.0 + i, 3920.0 + i, 3880.0 + i)
                for i in range(30)]
        _init_db(self.db, "sh000001", "daily", _bars(hist))

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def test_close_override_when_same_bar_time(self, monkeypatch):
        """早盘快照 close=3938.1 → 收盘 close=3946.68，应覆盖为收盘价。"""
        # 先写入早盘快照（bar_time 已存在，close 是盘中价）
        _init_db(self.db, "sh000001", "daily",
                 _bars([("2026-08-12", 3933.55, 3938.1, 3940.79, 3927.55)]))

        # mock 收盘后的 API：返回同 bar_time 但 close=3946.68
        monkeypatch.setattr(
            mod, "fetch_latest_klines",
            lambda code, klt, count: _bars(
                [("2026-08-12", 3933.55, 3946.68, 3950.62, 3927.55)]),
        )
        monkeypatch.setattr(mod, "DB_PATH", self.db)

        result = mod.update_one("sh000001", "daily")

        assert result["status"] == "updated", result
        assert _read_close(self.db, "sh000001", "daily", "2026-08-12") == 3946.68

    def test_no_change_returns_up_to_date(self, monkeypatch):
        """close 不变 → 不重复写，返回 up_to_date。"""
        _init_db(self.db, "sh000001", "daily",
                 _bars([("2026-08-12", 3933.55, 3946.68, 3950.62, 3927.55)]))

        monkeypatch.setattr(
            mod, "fetch_latest_klines",
            lambda code, klt, count: _bars(
                [("2026-08-12", 3933.55, 3946.68, 3950.62, 3927.55)]),
        )
        monkeypatch.setattr(mod, "DB_PATH", self.db)

        result = mod.update_one("sh000001", "daily")

        assert result["status"] in ("up_to_date", "no_new_bars"), result
        assert _read_close(self.db, "sh000001", "daily", "2026-08-12") == 3946.68
