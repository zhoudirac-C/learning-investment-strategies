"""早盘盘前盲判测试（mock LLM，不触网）。"""
import json
import tempfile
from pathlib import Path

from qing_investment.kline_cache import init_db, save_index_klines, save_klines
from investment_engine.shadow import premarket as pm


def _klines(code: str, closes: list[float]) -> list[dict]:
    return [
        {"code": code, "date": f"2026-06-{i + 1:02d}", "open": c, "high": c * 1.02,
         "low": c * 0.98, "close": c, "volume": 1000 + i * 10,
         "turnover": 1.5, "amplitude": 4.0, "pct_change": 0.5}
        for i, c in enumerate(closes)
    ]


def _overnight(day: str) -> dict:
    return {"date": day, "fetched_at": f"{day}T08:20:00",
            "themes": [{"id": "ai", "name": "AI算力",
                        "stocks": [{"symbol": "NVDA", "name": "英伟达",
                                    "price": 120.0, "prev_close": 115.0,
                                    "pct_change": 4.35, "secid": "105.NVDA",
                                    "earnings_note": ""}]}],
            "errors": [], "note": "涨跌幅为昨夜美股收盘数据"}


class TestPremarketPrompt:
    def test_prompt_passes_leakage_assertion(self):
        """盘前 prompt 边界=预测日，含隔夜外盘仍须过防泄漏。"""
        db = Path(tempfile.gettempdir()) / f"test_pre_{id(self)}.db"
        init_db(db_path=db)
        save_index_klines("sh000300", _klines("IDX000300", [4000.0 + i for i in range(30)]),
                          db_path=db)
        save_klines("002371.SZ", _klines("002371.SZ", [10.0 + i * 0.1 for i in range(30)]),
                    db_path=db)

        pack = pm.build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"),
                                   db_path=db)
        overnight = _overnight("2026-06-16")
        text = pm._pack_to_premarket_prompt(pack, "2026-06-16", overnight)
        assert "2026-06-16" in text  # 边界日期=预测日
        assert "英伟达" in text and "4.35" in text  # 隔夜外盘已注入
        assert "2026-06-17" not in text  # 无未来日期

    def test_prompt_without_overnight(self):
        """隔夜外盘缺失时不注入该块，仍可出 prompt。"""
        db = Path(tempfile.gettempdir()) / f"test_pre2_{id(self)}.db"
        init_db(db_path=db)
        save_index_klines("sh000300", _klines("IDX000300", [4000.0 + i for i in range(30)]),
                          db_path=db)
        pack = pm.build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"),
                                   db_path=db)
        text = pm._pack_to_premarket_prompt(pack, "2026-06-16", None)
        assert "overnight_us" not in text


class TestRunPredictPremarket:
    def test_no_prev_day_returns_no_data(self):
        db = Path(tempfile.gettempdir()) / f"test_pre3_{id(self)}.db"
        init_db(db_path=db)
        rec = pm.run_predict_premarket("2026-06-01", config_dir="config/stock_monitor",
                                       db_path=db)
        assert rec["status"] == "no_data"

    def test_skips_completed(self, monkeypatch, tmp_path):
        db = Path(tempfile.gettempdir()) / f"test_pre4_{id(self)}.db"
        init_db(db_path=db)
        save_index_klines("sh000300", _klines("IDX000300", [4000.0 + i for i in range(30)]),
                          db_path=db)
        pred_dir = Path(tmp_path)
        (pred_dir / "2026-06-16-pre.json").write_text(
            json.dumps({"date": "2026-06-16", "status": "pending_maturity"}),
            encoding="utf-8")
        rec = pm.run_predict_premarket("2026-06-16", config_dir="config/stock_monitor",
                                       db_path=db, pred_dir=pred_dir)
        assert rec["status"] == "skipped"
