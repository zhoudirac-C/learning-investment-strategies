"""每日数据包构建与防泄漏测试。"""
import json
import tempfile
from pathlib import Path

import pytest

from qing_investment.kline_cache import init_db, save_index_klines, save_klines
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
        save_index_klines("sh000300", _klines("IDX000300", [4000.0 + i for i in range(30)]), db_path=self.db)

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
        # TDX 板块归属（sectors 多板块 + direction 取首个），均为静态字段
        assert set(s) == {"code", "name", "direction", "sectors", "close", "pct", "turnover", "pos20"}

    def test_direction_pool_has_no_time_varying_fields(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        for d in pack["directions"]:
            # 只允许静态字段：id/name/member_count/local_count（current_stage 等时变字段不得进入）
            assert set(d) <= {"id", "name", "member_count", "local_count"}
            assert "current_stage" not in d and "stage" not in d

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
        save_index_klines("sh000300", _klines("IDX000300", [4000.0 + i for i in range(30)]),
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
        self.research = Path(tempfile.mkdtemp())
        (self.research / "notices").mkdir(parents=True)
        (self.research / "reports").mkdir(parents=True)
        (self.research / "notices" / "2026-06-30.json").write_text(json.dumps([
            {"code": "600664", "name": "哈药股份",
             "title": "哈药股份:2026年半年度报告", "type": "定期报告",
             "date": "2026-06-30", "url": ""},
        ], ensure_ascii=False), encoding="utf-8")
        (self.research / "reports" / "2026-06-30.json").write_text(json.dumps([
            {"info_code": "X1", "title": "医药行业周报：创新药景气延续",
             "org": "测试证券", "publish_date": "2026-06-30", "qtype": "1",
             "qtype_name": "行业研报", "industry_name": "医药",
             "stock_code": "", "stock_name": "", "rating": ""},
        ], ensure_ascii=False), encoding="utf-8")
        self.ff = Path(tempfile.mkdtemp())
        (self.ff / "20260630.json").write_text(json.dumps({
            "date": "2026-06-30", "fetched_at": "2026-06-30T15:40:00",
            "industry": {"即时": [{"行业": "医药", "净额": 3.2,
                                   "行业-涨跌幅": 1.1, "领涨股": "哈药股份"}],
                         "3日排行": [], "5日排行": [], "10日排行": []},
            "concept": {"即时": [], "3日排行": [], "5日排行": [], "10日排行": []},
            "errors": [],
        }, ensure_ascii=False), encoding="utf-8")
        self.ia = Path(tempfile.mkdtemp())
        self.si = Path(tempfile.mkdtemp())
        (self.si / "20260630.json").write_text(json.dumps({
            "date": "2026-06-30", "pm_lead_camp": "防御",
            "sectors": [{"code": "880471", "name": "银行", "camp": "防御",
                         "day_pct": 1.0, "am_pct": 0.5, "pm_pct": 0.5,
                         "marker": "真强势"}],
        }, ensure_ascii=False), encoding="utf-8")
        self.gm = Path(tempfile.mkdtemp())
        (self.gm / "20260630.json").write_text(json.dumps({
            "date": "2026-06-30", "fetched_at": "2026-06-30T16:35:00",
            "美股三指数": {"纳指": {"symbol": "^IXIC", "session": "2026-06-29",
                                  "close": 26000.0, "pct": 0.15}},
            "美债收益率": {"10Y": {"symbol": "^TNX", "session": "2026-06-29",
                                 "yield": 4.65, "chg_bp": -5.3}},
            "errors": [], "note": "n",
        }, ensure_ascii=False), encoding="utf-8")

    def _build(self, day: str, **kw):
        return build_daily_pack(day, config_dir=Path("config/stock_monitor"),
                                db_path=self.db, kpl_root=self.kpl, em_root=self.em,
                                lp_root=self.lp, ic_root=self.ic,
                                research_root=self.research, ff_root=self.ff,
                                ia_root=self.ia, si_root=self.si,
                                gm_root=self.gm, **kw)

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
        pack = self._build("2026-06-30")
        assert pack["emotion"]["daban"]["今日涨停"] == 99
        assert pack["emotion"]["daban"]["封板率_pct"] == 87.6
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
        # 板块分时强度块
        assert pack["sector_intraday"]["pm_lead_camp"] == "防御"
        assert pack["sector_intraday"]["sectors"][0]["marker"] == "真强势"
        # 全球宏观块（fetched_at 可能晚于回放日，不进包）
        assert pack["global_macro"]["美债收益率"]["10Y"]["yield"] == 4.65
        assert pack["global_macro"]["美股三指数"]["纳指"]["pct"] == 0.15
        assert "fetched_at" not in pack["global_macro"]
        assert "missing" not in pack
        pack_to_prompt(pack)  # 过防泄漏断言

    def test_eastmoney_lhb_preferred(self):
        self._write_em_lhb()
        pack = self._build("2026-06-30")
        lhb = pack["lhb"]
        assert lhb["source"] == "eastmoney" and lhb["count"] == 2
        # 按 |net_amt| 降序：风华高科(500) 在哈药股份(-100) 前
        assert [i["code"] for i in lhb["items"]] == ["000636", "600664"]
        # 席位封顶 5
        assert len(lhb["items"][1]["buy_seats"]) == 5
        pack_to_prompt(pack)  # 过防泄漏断言

    def test_missing_blocks_annotated(self):
        pack = self._build("2026-06-29")
        assert pack["missing"] == ["kpl_emotion", "kpl_news_titles", "kpl_lhb",
                                   "limit_pool", "intraday_changes",
                                   "research", "fund_flow", "sector_intraday",
                                   "global_macro"]
        assert "emotion" not in pack


def test_index_codes_expanded():
    assert set(INDEX_CODES) == {"IDX000300", "IDX000001", "IDX399006",
                                "IDX399001", "IDX000852",
                                "IDX000932", "IDX880823"}  # 中证2000/微盘股（D7 可选项）


class TestP2DataBlocks:
    """批次 P1/P2 新数据块：research/catalysts/fund_flow/jgmmtj/broken_boards/intraday_amount 读盘。"""

    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_ds4_{id(self)}.db"
        init_db(db_path=self.db)
        save_index_klines("sh000300", _klines("IDX000300", [4000.0 + i for i in range(30)]),
                          db_path=self.db)
        self.kpl = Path(tempfile.mkdtemp())
        (self.kpl / "emotion").mkdir(parents=True)
        (self.kpl / "news").mkdir(parents=True)
        (self.kpl / "lhb").mkdir(parents=True)
        self.em = Path(tempfile.mkdtemp())
        (self.em / "lhb").mkdir(parents=True)
        self.lp = Path(tempfile.mkdtemp())
        self.ic = Path(tempfile.mkdtemp())
        self.research = Path(tempfile.mkdtemp())
        (self.research / "notices").mkdir(parents=True)
        (self.research / "reports").mkdir(parents=True)
        self.ff = Path(tempfile.mkdtemp())
        self.ia = Path(tempfile.mkdtemp())

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def _build(self, day: str = "2026-06-30", **kw):
        return build_daily_pack(day, config_dir=Path("config/stock_monitor"),
                                db_path=self.db, kpl_root=self.kpl, em_root=self.em,
                                lp_root=self.lp, ic_root=self.ic,
                                research_root=self.research, ff_root=self.ff,
                                ia_root=self.ia, **kw)

    def _write_notices(self, day: str, items: list[dict]):
        (self.research / "notices" / f"{day}.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8")

    def _write_reports(self, day: str, items: list[dict]):
        (self.research / "reports" / f"{day}.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8")

    def _write_kpl_news(self, day: str, items: list[dict]):
        d = self.kpl / "news" / day
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.json").write_text(json.dumps(items, ensure_ascii=False),
                                      encoding="utf-8")

    @staticmethod
    def _ff_instant_rows():
        rows = [{"行业": f"流入板块{i}", "净额": float(16 - i),
                 "行业-涨跌幅": 1.0, "领涨股": f"领涨{i}"} for i in range(1, 16)]
        rows += [{"行业": f"流出板块{i}", "净额": float(-(11 - i)),
                  "行业-涨跌幅": -1.0, "领涨股": f"领跌{i}"} for i in range(1, 11)]
        return rows

    def _write_fund_flow(self, day: str = "2026-06-30", *, errors=None, null_windows=False):
        if null_windows:
            industry = {w: None for w in ("即时", "3日排行", "5日排行", "10日排行")}
            concept = {w: None for w in ("即时", "3日排行", "5日排行", "10日排行")}
        else:
            multi = [{"行业": f"持续板块{i}", "净额": float(7 - i), "阶段涨跌幅": "3.0%"}
                     for i in range(1, 7)]
            industry = {"即时": self._ff_instant_rows(), "3日排行": multi,
                        "5日排行": multi, "10日排行": multi}
            concept = {"即时": self._ff_instant_rows()[:5],
                       "3日排行": [], "5日排行": [], "10日排行": []}
        (self.ff / f"{day.replace('-', '')}.json").write_text(json.dumps({
            "date": day, "fetched_at": f"{day}T15:40:00",
            "industry": industry, "concept": concept, "errors": errors or [],
        }, ensure_ascii=False), encoding="utf-8")

    # ---- research 块（C6） ----

    def test_research_block_present(self):
        self._write_notices("2026-06-30", [
            {"code": "600664", "name": "哈药股份", "title": f"哈药股份:公告第{i}号",
             "type": "临时公告", "date": "2026-06-30", "url": ""}
            for i in range(31)])
        self._write_reports("2026-06-30", [
            {"info_code": "X1", "title": "医药行业周报", "org": "测试证券",
             "publish_date": "2026-06-30", "qtype": "1", "qtype_name": "行业研报",
             "industry_name": "医药", "stock_code": "", "stock_name": "", "rating": ""},
        ])
        pack = self._build()
        research = pack["research"]
        assert len(research["notices"]) == 30  # 封顶 30
        assert research["notices_truncated"] == "30/31"
        assert research["notices"][0]["title"] == "哈药股份:公告第0号"
        assert research["notices"][0]["code"] == "600664"
        assert research["reports"][0]["title"] == "医药行业周报"
        assert research["reports"][0]["org"] == "测试证券"
        assert "research" not in pack.get("missing", [])
        pack_to_prompt(pack)  # 过防泄漏断言

    def test_research_missing_registered(self):
        pack = self._build()
        assert "research" not in pack
        assert "research" in pack["missing"]

    def test_research_partial_file_ok(self):
        self._write_reports("2026-06-30", [
            {"info_code": "X1", "title": "策略周报", "org": "测试证券",
             "publish_date": "2026-06-30", "qtype": "2", "qtype_name": "策略报告",
             "industry_name": "", "stock_code": "", "stock_name": "", "rating": ""},
        ])
        pack = self._build()
        assert pack["research"]["reports"][0]["title"] == "策略周报"
        assert "notices" not in pack["research"]
        assert "research" not in pack.get("missing", [])

    def test_research_leakage_raises(self):
        self._write_notices("2026-06-30", [
            {"code": "600664", "name": "哈药股份", "title": "某UP主推荐买入哈药股份",
             "type": "临时公告", "date": "2026-06-30", "url": ""},
        ])
        with pytest.raises(LeakageError):
            self._build()

    # ---- fund_flow 块（C1/C4） ----

    def test_fund_flow_block_summary(self):
        self._write_fund_flow()
        pack = self._build()
        ff = pack["fund_flow"]
        inflow = ff["行业即时"]["净流入top10"]
        outflow = ff["行业即时"]["净流出top10"]
        assert len(inflow) == 10 and inflow[0]["净额"] == 15.0
        assert inflow[0]["行业"] == "流入板块1"
        assert len(outflow) == 10 and outflow[0]["净额"] == -10.0
        assert all(r["净额"] < 0 for r in outflow)
        # 概念即时同构
        assert len(ff["概念即时"]["净流入top10"]) == 5
        # 行业多日窗口各 top5（持续性佐证）
        for w in ("3日排行", "5日排行", "10日排行"):
            top5 = ff["行业多日"][w]["净流入top5"]
            assert len(top5) == 5 and top5[0]["净额"] == 6.0
            assert top5[0]["行业"] == "持续板块1"
        assert "fetched_at" not in ff  # 拉取时刻可能晚于回放日，不得进包
        assert "fund_flow" not in pack.get("missing", [])
        pack_to_prompt(pack)  # 过防泄漏断言

    def test_fund_flow_partial_errors_noted(self):
        self._write_fund_flow(errors=["concept/即时: RemoteDisconnected"])
        pack = self._build()
        assert "errors_note" in pack["fund_flow"]
        assert "fund_flow" not in pack.get("missing", [])

    def test_fund_flow_missing_or_all_errors(self):
        pack = self._build()  # 无文件
        assert "fund_flow" not in pack
        assert "fund_flow" in pack["missing"]
        self._write_fund_flow(null_windows=True,
                              errors=["industry/即时: x"] * 8)
        pack = self._build()
        assert "fund_flow" not in pack
        assert "fund_flow" in pack["missing"]

    # ---- lhb jgmmtj（C3 机构席位汇总） ----

    def _write_em_lhb(self, jgmmtj):
        (self.em / "lhb" / "2026-06-30.json").write_text(json.dumps({
            "source": "eastmoney", "trade_date": "2026-06-30", "stock_count": 1,
            "items": [{"code": "600664", "name": "哈药股份", "net_amt": 500.0,
                       "buy_seats": [], "sell_seats": []}],
            "jgmmtj": jgmmtj, "note": "",
        }, ensure_ascii=False), encoding="utf-8")

    def test_lhb_jgmmtj_summary(self):
        self._write_em_lhb([
            {"代码": "000001", "名称": "买入王", "机构买入净额": 2.6e8,
             "买方机构数": 4, "卖方机构数": 1, "机构净买额占总成交额比": 4.56,
             "上榜日期": "2026-06-30"},
            {"代码": "000002", "名称": "买入二", "机构买入净额": 1.0e8,
             "买方机构数": 2, "卖方机构数": 1, "机构净买额占总成交额比": 1.2,
             "上榜日期": "2026-06-30"},
            {"代码": "000003", "名称": "买入三", "机构买入净额": 0.5e8,
             "买方机构数": 1, "卖方机构数": 0, "机构净买额占总成交额比": 0.8,
             "上榜日期": "2026-06-30"},
            {"代码": "000004", "名称": "卖出一", "机构买入净额": -0.3e8,
             "买方机构数": 0, "卖方机构数": 1, "机构净买额占总成交额比": -0.5,
             "上榜日期": "2026-06-30"},
            {"代码": "000005", "名称": "卖出二", "机构买入净额": -0.8e8,
             "买方机构数": 1, "卖方机构数": 3, "机构净买额占总成交额比": -1.1,
             "上榜日期": "2026-06-30"},
            {"代码": "000006", "名称": "卖出王", "机构买入净额": -1.5e8,
             "买方机构数": 0, "卖方机构数": 5, "机构净买额占总成交额比": -2.3,
             "上榜日期": "2026-06-30"},
        ])
        pack = self._build()
        jg = pack["lhb"]["jgmmtj"]
        assert jg["净买入top5"][0]["名称"] == "买入王"
        assert jg["净买入top5"][0]["机构买入净额_亿"] == 2.6
        assert jg["净买入top5"][0]["买方机构数"] == 4
        assert jg["净卖出top5"][0]["名称"] == "卖出王"
        assert jg["净卖出top5"][0]["机构买入净额_亿"] == -1.5
        assert jg["净买入家数"] == 3 and jg["净卖出家数"] == 3
        assert pack["lhb"]["count"] == 1  # 既有席位明细不受影响
        pack_to_prompt(pack)  # 过防泄漏断言

    def test_lhb_jgmmtj_none_ignored(self):
        self._write_em_lhb(None)  # 拉取失败形态：None 不影响其余部分
        pack = self._build()
        assert "jgmmtj" not in pack["lhb"]
        assert pack["lhb"]["items"][0]["code"] == "600664"

    # ---- limit_pool broken_boards（C5 断板） ----

    def test_limit_pool_broken_boards(self):
        (self.lp / "20260630.json").write_text(json.dumps({
            "date": "2026-06-30", "zt_count": 3, "zb_count": 1, "max_lbc": 3,
            "ladder": {}, "auction_sealed": [], "compare": {},
            "zt_items": [], "zb_items": [],
            "broken_boards": [
                {"code": "000936", "name": "华西股份", "prev_lbc": 3,
                 "chg_today": -4.88, "status": "温和断板"},
                {"code": "000937", "name": "冲高股", "prev_lbc": 2,
                 "chg_today": 3.1, "status": "冲板未封"},
            ],
            "broken_boards_note": "断板=昨连板今日未封",
        }, ensure_ascii=False), encoding="utf-8")
        pack = self._build()
        lp = pack["limit_pool"]
        assert lp["broken_boards"][0]["status"] == "温和断板"
        assert lp["broken_boards"][1]["name"] == "冲高股"
        assert lp["broken_boards_note"] == "断板=昨连板今日未封"
        pack_to_prompt(pack)  # 过防泄漏断言

    def test_limit_pool_without_broken_boards(self):
        (self.lp / "20260630.json").write_text(json.dumps({
            "date": "2026-06-30", "zt_count": 1, "zb_count": 0, "max_lbc": 1,
            "ladder": {}, "auction_sealed": [], "compare": {},
            "zt_items": [], "zb_items": [],
        }, ensure_ascii=False), encoding="utf-8")
        pack = self._build()
        assert "broken_boards" not in pack["limit_pool"]

    # ---- intraday_amount 读盘优先（P2 分时腿接线） ----

    def test_intraday_amount_read_from_disk(self, monkeypatch):
        (self.ia / "20260630.json").write_text(json.dumps({
            "date": "2026-06-30",
            "分时": [{"时点": "10:30", "累计_亿": 10943.0, "预估全天_亿": 43772.0}],
            "开盘预估全天_亿": 43772.0, "尾盘实际全天_亿": 23875.0,
            "形态": "冲量滑落（全天缩量）",
        }, ensure_ascii=False), encoding="utf-8")

        def _boom(tdx=None):
            raise AssertionError("有落盘文件时不得走实时拉取")

        monkeypatch.setattr("investment_engine.intraday_amount.compute_intraday_amount", _boom)
        pack = self._build()
        assert pack["intraday_amount"]["形态"] == "冲量滑落（全天缩量）"
        assert pack["intraday_amount"]["尾盘实际全天_亿"] == 23875.0

    def test_intraday_amount_fallback_compute(self, monkeypatch):
        monkeypatch.setattr(
            "investment_engine.intraday_amount.compute_intraday_amount",
            lambda tdx=None: {"date": "2026-06-30", "分时": [],
                              "开盘预估全天_亿": 100.0, "尾盘实际全天_亿": 90.0,
                              "形态": "平量"})
        pack = self._build()
        assert pack["intraday_amount"]["形态"] == "平量"

    def test_intraday_amount_compute_day_mismatch(self, monkeypatch):
        """实时拉取得到的是其他交易日数据时，视同缺失（防历史回放串数据）。"""
        monkeypatch.setattr(
            "investment_engine.intraday_amount.compute_intraday_amount",
            lambda tdx=None: {"date": "2026-08-17", "分时": [],
                              "开盘预估全天_亿": 100.0, "尾盘实际全天_亿": 90.0,
                              "形态": "平量"})
        pack = self._build("2026-06-30")
        assert pack["intraday_amount"] is None

    # ---- catalysts_since_prev_day（C2） ----

    def test_no_catalysts_without_target_day(self):
        pack = self._build()
        assert "catalysts_since_prev_day" not in pack

    def test_catalysts_collected(self):
        self._write_notices("2026-07-01", [
            {"code": "600664", "name": "哈药股份", "title": "哈药股份:签订重大合同",
             "type": "临时公告", "date": "2026-07-01", "url": ""},
        ])
        self._write_reports("2026-07-01", [
            {"info_code": "X2", "title": "创新药深度报告", "org": "测试证券",
             "publish_date": "2026-07-01", "qtype": "1", "qtype_name": "行业研报",
             "industry_name": "医药", "stock_code": "600664", "stock_name": "哈药股份",
             "rating": "买入"},
        ])
        self._write_kpl_news("2026-07-01", [
            {"id": 1, "title": "医药板块午后异动", "stocks": [{"StockID": "600664"}]},
        ])
        pack = self._build("2026-06-30", target_day="2026-07-01")
        cats = pack["catalysts_since_prev_day"]
        assert len(cats) == 3
        sources = {c["source"] for c in cats}
        assert sources == {"公告", "研报", "资讯"}
        assert all(c["date"] == "2026-07-01" for c in cats)
        news = next(c for c in cats if c["source"] == "资讯")
        assert news["stocks"] == ["600664"]
        assert "catalysts" not in pack.get("missing", [])

    def test_catalysts_empty_list_when_no_data(self):
        pack = self._build("2026-06-30", target_day="2026-07-01")
        assert pack["catalysts_since_prev_day"] == []
        assert "catalysts" not in pack.get("missing", [])

    def test_catalysts_skip_day_itself(self):
        """区间 (day, target_day]：day 当日内容归 research/news_titles，不进 catalysts。"""
        self._write_notices("2026-06-30", [
            {"code": "600664", "name": "哈药股份", "title": "哈药股份:当日公告",
             "type": "临时公告", "date": "2026-06-30", "url": ""},
        ])
        pack = self._build("2026-06-30", target_day="2026-07-01")
        assert pack["catalysts_since_prev_day"] == []

    def test_catalysts_capped_at_60(self):
        self._write_notices("2026-07-01", [
            {"code": "600664", "name": "哈药股份", "title": f"公告第{i}号",
             "type": "临时公告", "date": "2026-07-01", "url": ""}
            for i in range(61)])
        pack = self._build("2026-06-30", target_day="2026-07-01")
        assert len(pack["catalysts_since_prev_day"]) == 60

    def test_catalysts_leakage_raises(self):
        self._write_kpl_news("2026-07-01", [
            {"id": 1, "title": "博主复盘：明日看涨", "stocks": []},
        ])
        with pytest.raises(LeakageError):
            self._build("2026-06-30", target_day="2026-07-01")
