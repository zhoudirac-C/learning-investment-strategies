"""每日数据包构建与防泄漏测试。"""
import json
import tempfile
from pathlib import Path

import pytest

from qing_investment.kline_cache import init_db, save_klines
from investment_engine.blindtest.dataset import (
    INDEX_CODES, LeakageError, assert_no_leakage, build_daily_pack, pack_to_prompt,
    trading_days,
)


def _klines(code: str, closes: list[float]) -> list[dict]:
    return [
        {"code": code, "date": f"2026-06-{i + 1:02d}", "open": c, "high": c * 1.02,
         "low": c * 0.98, "close": c, "volume": 1000 + i * 10,
         "turnover": 1.5, "amplitude": 4.0, "pct_change": 0.5}
        for i, c in enumerate(closes)
    ]


class TestTradingDays:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_ds_{id(self)}.db"
        init_db(db_path=self.db)
        save_klines("002371", _klines("002371", [10.0] * 30), db_path=self.db)

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def test_days_from_cache(self):
        days = trading_days("2026-06-01", "2026-06-30", db_path=self.db)
        assert days[0] == "2026-06-01" and len(days) == 30


class TestAssertNoLeakage:
    def test_future_date_rejected(self):
        with pytest.raises(LeakageError, match="2026-08-01"):
            assert_no_leakage("截至 2026-07-01 数据。参考 2026-08-01 走势", "2026-07-01")

    def test_up_words_rejected(self):
        for w in ("UP", "青枫浦", "博主"):
            with pytest.raises(LeakageError):
                assert_no_leakage(f"某 {w} 观点", "2026-07-01")

    def test_clean_text_passes(self):
        assert_no_leakage("2026-07-01 收盘综述：量能 1.2 万亿", "2026-07-01")


class TestBuildDailyPack:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_ds2_{id(self)}.db"
        init_db(db_path=self.db)
        save_klines("002371.SZ", _klines("002371.SZ", [10.0 + i * 0.1 for i in range(30)]), db_path=self.db)
        save_klines("IDX000300", _klines("IDX000300", [4000.0 + i for i in range(30)]), db_path=self.db)

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def test_pack_truncates_at_day(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        assert pack["date"] == "2026-06-15"
        idx = pack["index"]["IDX000300"]
        assert idx[-1]["d"] == "2026-06-15"  # 数据截至当日，无未来
        assert len(idx) == 15

    def test_pack_stock_entry_fields(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        s = next(x for x in pack["stocks"] if x["code"] == "002371")
        assert set(s) == {"code", "name", "direction", "close", "pct", "turnover", "pos20"}

    def test_direction_pool_has_no_time_varying_fields(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        for d in pack["directions"]:
            assert set(d) == {"id", "name"}  # current_stage 等时变字段不得进入

    def test_prompt_passes_leakage_assertion(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        text = pack_to_prompt(pack)
        assert_no_leakage(text, "2026-06-15")  # 自身产出必须过自家断言

    def test_core_patterns_injected(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        core = {p["pattern_id"] for p in pack["core_patterns"]}
        assert {"sentiment_cycle", "mainline_identification"} <= core
        for p in pack["core_patterns"]:
            assert p["steps"] and p["falsification"]
            assert "source_raw" not in p  # 来源字段不得入包
        pack_to_prompt(pack)  # 正文注入后仍须过防泄漏断言


class TestKplBlocks:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_ds3_{id(self)}.db"
        init_db(db_path=self.db)
        save_klines("IDX000300", _klines("IDX000300", [4000.0 + i for i in range(30)]),
                    db_path=self.db)
        self.kpl = Path(tempfile.mkdtemp())
        (self.kpl / "emotion").mkdir(parents=True)
        (self.kpl / "news" / "2026-06-30").mkdir(parents=True)
        (self.kpl / "lhb").mkdir(parents=True)
        (self.kpl / "emotion" / "2026-06-30.json").write_text(json.dumps({
            "daban": {"tZhangTing": 99, "tFengBan": 87.6},
            "lianban": [["600664", "哈药股份", 9.94, 0, "2连板", "医药", "创新药;2"]],
            "fengkou": [{"StockID": "002655", "StockName": "共达电声"}],
            "bankuai": [["医药", "1.61", 801045]],
        }, ensure_ascii=False), encoding="utf-8")
        (self.kpl / "news" / "2026-06-30" / "index.json").write_text(json.dumps([
            {"id": 1, "title": "测试资讯", "stocks": [{"StockID": "600664"}], "fetched": True},
        ], ensure_ascii=False), encoding="utf-8")
        (self.kpl / "lhb" / "2026-06-30.json").write_text(json.dumps({
            "disclosure_day": "2026-06-30",
            "list": {"2": [{"StockID": "600664"}], "3": []},
            "entry_count": 1, "note": "",
        }, ensure_ascii=False), encoding="utf-8")
        self.em = Path(tempfile.mkdtemp())
        (self.em / "lhb").mkdir(parents=True)
        self.lp = Path(tempfile.mkdtemp())
        (self.lp / "20260630.json").write_text(json.dumps({
            "date": "2026-06-30", "zt_count": 3, "zb_count": 1, "max_lbc": 3,
            "ladder": {"3板": ["秦安股份"], "2板": ["哈药股份"]},
            "auction_sealed": ["蓝盾光电"],
            "compare": {"promotion_rate": 0.2, "fanbao": ["高争民爆"]},
            "zt_items": [{"code": "603758", "name": "秦安股份", "lbc": 3, "fund": 1e8},
                         {"code": "002826", "name": "首板股", "lbc": 1, "fund": 5e7}],
            "zb_items": [{"code": "600000", "name": "炸板股"}],
        }, ensure_ascii=False), encoding="utf-8")
        self.ic = Path(tempfile.mkdtemp())
        (self.ic / "20260630.json").write_text(json.dumps({
            "date": "2026-06-30",
            "counts": {"封涨停板": 2, "大笔买入": 1},
            "types": {"封涨停板": [
                {"time": "14:54", "code": "600721", "name": "百花医药",
                 "info": "14.03,4042894,14.03,0.100392"}]},
            "total": 3,
        }, ensure_ascii=False), encoding="utf-8")

    def _write_em_lhb(self, day: str = "2026-06-30"):
        seats = [{"name": f"席位{i}", "buy": i, "sell": 0, "net": i} for i in range(7)]
        (self.em / "lhb" / f"{day}.json").write_text(json.dumps({
            "source": "eastmoney", "trade_date": day, "stock_count": 2,
            "items": [
                {"code": "600664", "name": "哈药股份", "net_amt": -100.0,
                 "buy_seats": seats, "sell_seats": seats},
                {"code": "000636", "name": "风华高科", "net_amt": 500.0,
                 "buy_seats": seats[:1], "sell_seats": []},
            ], "note": "",
        }, ensure_ascii=False), encoding="utf-8")

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def test_blocks_present(self):
        pack = build_daily_pack("2026-06-30", config_dir=Path("config/stock_monitor"),
                                db_path=self.db, kpl_root=self.kpl, em_root=self.em,
                                lp_root=self.lp, ic_root=self.ic)
        assert pack["emotion"]["daban"]["tZhangTing"] == 99
        assert pack["emotion"]["bankuai"] == [["医药", "1.61"]]
        assert pack["emotion"]["fengkou_stocks"] == ["共达电声"]
        assert pack["news_titles"]["items"][0]["stocks"] == ["600664"]
        assert pack["lhb"]["source"] == "kpl"  # 东财缺失时回退 KPL
        assert pack["lhb"]["count"] == 1
        # 涨停梯队块
        lp = pack["limit_pool"]
        assert lp["max_lbc"] == 3 and lp["ladder"] == {"3板": ["秦安股份"], "2板": ["哈药股份"]}
        assert lp["auction_sealed"] == ["蓝盾光电"]
        assert lp["compare"]["promotion_rate"] == 0.2
        assert lp["zt_items"][0]["name"] == "秦安股份"  # 按封单额降序
        # 盘中异动块
        assert pack["intraday_changes"]["counts"]["封涨停板"] == 2
        assert "missing" not in pack
        pack_to_prompt(pack)  # 过防泄漏断言

    def test_eastmoney_lhb_preferred(self):
        self._write_em_lhb()
        pack = build_daily_pack("2026-06-30", config_dir=Path("config/stock_monitor"),
                                db_path=self.db, kpl_root=self.kpl, em_root=self.em,
                                lp_root=self.lp, ic_root=self.ic)
        lhb = pack["lhb"]
        assert lhb["source"] == "eastmoney" and lhb["count"] == 2
        # 按 |net_amt| 降序：风华高科(500) 在哈药股份(-100) 前
        assert [i["code"] for i in lhb["items"]] == ["000636", "600664"]
        # 席位封顶 5
        assert len(lhb["items"][1]["buy_seats"]) == 5
        pack_to_prompt(pack)  # 过防泄漏断言

    def test_missing_blocks_annotated(self):
        pack = build_daily_pack("2026-06-29", config_dir=Path("config/stock_monitor"),
                                db_path=self.db, kpl_root=self.kpl, em_root=self.em,
                                lp_root=self.lp, ic_root=self.ic)
        assert pack["missing"] == ["kpl_emotion", "kpl_news_titles", "kpl_lhb",
                                   "limit_pool", "intraday_changes"]
        assert "emotion" not in pack


def test_index_codes_expanded():
    assert set(INDEX_CODES) == {"IDX000300", "IDX000001", "IDX399006",
                                "IDX399001", "IDX000852"}
