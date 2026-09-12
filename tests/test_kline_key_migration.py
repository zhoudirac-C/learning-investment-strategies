"""migrate_kline_keys —— 存量双键数据一次性迁移到规范后缀键的契约测试。

碰撞规则：多个旧键归一到同一规范键时，按 MAX(trade_date) 取更新者整序列，
输者整序列丢弃（各键序列都是 90 天完整窗口覆盖写，无缺日互补价值）。
"""
import sqlite3

import pytest

from qing_investment.kline_cache import init_db, migrate_kline_keys


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "kline_cache.db"
    init_db(db_path=p)
    return p


def _insert(conn, code, rows):
    conn.executemany(
        "INSERT INTO stocks_kline (code, trade_date, close, volume) VALUES (?, ?, ?, ?)",
        [(code, d, c, 1000.0) for d, c in rows],
    )


class TestMigrate:
    def test_simple_rekey_bare_to_suffix(self, db):
        conn = sqlite3.connect(db)
        _insert(conn, "002371", [("2026-09-10", 10.5), ("2026-09-11", 10.6)])
        conn.commit()
        conn.close()

        report = migrate_kline_keys(db_path=db)
        assert report["rekeyed"]["002371"] == "002371.SZ"

        conn = sqlite3.connect(db)
        keys = dict(conn.execute("SELECT code, COUNT(*) FROM stocks_kline GROUP BY code"))
        conn.close()
        assert keys == {"002371.SZ": 2}

    def test_collision_suffix_fresher_wins(self, db):
        conn = sqlite3.connect(db)
        _insert(conn, "000021", [("2026-06-23", 9.0), ("2026-06-24", 9.1)])
        _insert(conn, "000021.SZ", [("2026-09-09", 10.0), ("2026-09-10", 10.1)])
        conn.commit()
        conn.close()

        report = migrate_kline_keys(db_path=db)
        assert report["collisions"] == ["000021"]

        conn = sqlite3.connect(db)
        keys = dict(conn.execute("SELECT code, COUNT(*) FROM stocks_kline GROUP BY code"))
        conn.close()
        # 后缀键更新 → 保留后缀键数据，裸码旧序列丢弃
        assert keys == {"000021.SZ": 2}

    def test_collision_bare_fresher_wins_rekeyed(self, db):
        conn = sqlite3.connect(db)
        _insert(conn, "600363", [("2026-09-10", 15.1), ("2026-09-11", 15.2)])
        _insert(conn, "600363.SH", [("2026-06-29", 14.0), ("2026-06-30", 14.1)])
        conn.commit()
        conn.close()

        migrate_kline_keys(db_path=db)

        conn = sqlite3.connect(db)
        keys = dict(conn.execute("SELECT code, COUNT(*) FROM stocks_kline GROUP BY code"))
        conn.close()
        # 裸码更新 → 裸码数据挂到规范键名下（qfq 覆盖写会补齐新数据）
        assert keys == {"600363.SH": 2}

    def test_mislabeled_key_merged(self, db):
        # 000001.SH 实为平安银行（SZ）数据：与 000001 裸码同日重复，
        # 归一后同属 000001.SZ，按 MAX(trade_date) 取更新者
        conn = sqlite3.connect(db)
        _insert(conn, "000001", [("2026-09-09", 11.7), ("2026-09-11", 11.74)])
        _insert(conn, "000001.SH", [("2026-06-26", 10.23), ("2026-06-30", 10.05)])
        conn.commit()
        conn.close()

        migrate_kline_keys(db_path=db)

        conn = sqlite3.connect(db)
        keys = dict(conn.execute("SELECT code, COUNT(*) FROM stocks_kline GROUP BY code"))
        conn.close()
        assert keys == {"000001.SZ": 2}

    def test_idx_alias_untouched(self, db):
        conn = sqlite3.connect(db)
        _insert(conn, "IDX000001", [("2026-08-12", 3200.0)])
        conn.commit()
        conn.close()

        migrate_kline_keys(db_path=db)

        conn = sqlite3.connect(db)
        keys = dict(conn.execute("SELECT code, COUNT(*) FROM stocks_kline GROUP BY code"))
        conn.close()
        assert keys == {"IDX000001": 1}

    def test_dry_run_leaves_db_unchanged(self, db):
        conn = sqlite3.connect(db)
        _insert(conn, "002371", [("2026-09-10", 10.5)])
        conn.commit()
        conn.close()

        report = migrate_kline_keys(db_path=db, dry_run=True)
        assert report["rekeyed"] == {"002371": "002371.SZ"}

        conn = sqlite3.connect(db)
        keys = dict(conn.execute("SELECT code, COUNT(*) FROM stocks_kline GROUP BY code"))
        conn.close()
        assert keys == {"002371": 1}  # 未动

    def test_already_canonical_noop(self, db):
        conn = sqlite3.connect(db)
        _insert(conn, "000636.SZ", [("2026-09-11", 30.0)])
        conn.commit()
        conn.close()

        report = migrate_kline_keys(db_path=db)
        assert report["rekeyed"] == {} and report["collisions"] == []

        conn = sqlite3.connect(db)
        keys = dict(conn.execute("SELECT code, COUNT(*) FROM stocks_kline GROUP BY code"))
        conn.close()
        assert keys == {"000636.SZ": 1}
