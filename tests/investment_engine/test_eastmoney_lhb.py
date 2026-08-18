"""eastmoney_lhb.py 单元测试（monkeypatch _get_json，不触网）。"""

from __future__ import annotations

import json

import pytest

from investment_engine import eastmoney_lhb as em

DAY = "2026-08-10"

LIST_PAYLOAD = {
    "success": True,
    "result": {"count": 2, "data": [
        {"SECURITY_CODE": "000636", "SECURITY_NAME_ABBR": "风华高科",
         "TRADE_DATE": "2026-08-10 00:00:00", "EXPLANATION": "日振幅值达到15%的前5只证券",
         "CLOSE_PRICE": 61.7, "CHANGE_RATE": 5.8501,
         "BILLBOARD_NET_AMT": 420037061.81, "BILLBOARD_BUY_AMT": 1237023652.52,
         "BILLBOARD_SELL_AMT": 816986590.71, "TURNOVERRATE": 18.6024},
        {"SECURITY_CODE": "600664", "SECURITY_NAME_ABBR": "哈药股份",
         "TRADE_DATE": "2026-08-10 00:00:00", "EXPLANATION": "连续三个交易日内涨幅偏离值累计达20%",
         "CLOSE_PRICE": 6.22, "CHANGE_RATE": -8.12,
         "BILLBOARD_NET_AMT": -72951200.47, "BILLBOARD_BUY_AMT": 3e8,
         "BILLBOARD_SELL_AMT": 3.7e8, "TURNOVERRATE": 21.14},
    ]},
}
BUY_PAYLOAD = {"success": True, "result": {"count": 1, "data": [
    {"OPERATEDEPT_NAME": "深股通专用", "BUY": 595770243.99,
     "SELL": 376806190.74, "NET": 218964053.25},
]}}
SELL_PAYLOAD = {"success": True, "result": {"count": 1, "data": [
    {"OPERATEDEPT_NAME": "国信证券浙江互联网分公司", "BUY": 1.0,
     "SELL": 73715114.47, "NET": -73715113.47},
]}}
EMPTY_PAYLOAD = {"success": True, "result": None}


@pytest.fixture
def fake_http(monkeypatch):
    """按 reportName 路由的假响应；calls 记录请求参数。"""
    calls = []

    def _fake(params, timeout=10.0, retries=2):
        calls.append(params)
        rn = params["reportName"]
        if rn == "RPT_DAILYBILLBOARD_DETAILS":
            return LIST_PAYLOAD
        if rn == "RPT_BILLBOARD_DAILYDETAILSBUY":
            return BUY_PAYLOAD
        if rn == "RPT_BILLBOARD_DAILYDETAILSSELL":
            return SELL_PAYLOAD
        raise AssertionError(f"未预期 reportName: {rn}")

    monkeypatch.setattr(em, "_get_json", _fake)
    # 保持测试密闭：机构席位汇总不触真实 akshare（默认空表，需数据时用 fake_jgmmtj 覆盖）
    import akshare as ak
    import pandas as pd
    monkeypatch.setattr(ak, "stock_lhb_jgmmtj_em",
                        lambda start_date, end_date: pd.DataFrame())
    return calls


def test_fetch_daily_list_parses_rows(fake_http):
    rows = em.fetch_daily_list(DAY)
    assert len(rows) == 2 and rows[0]["SECURITY_CODE"] == "000636"
    assert fake_http[0]["filter"] == "(TRADE_DATE='2026-08-10')"


def test_fetch_seats_buy_sell(fake_http):
    seats = em.fetch_seats(DAY, "000636", sleep=0)
    assert seats["buy"] == [{"name": "深股通专用", "buy": 595770243.99,
                             "sell": 376806190.74, "net": 218964053.25}]
    assert seats["sell"][0]["name"] == "国信证券浙江互联网分公司"
    # 买/卖两个 reportName 都按 SECURITY_CODE 过滤
    assert [c["reportName"] for c in fake_http] == [
        "RPT_BILLBOARD_DAILYDETAILSBUY", "RPT_BILLBOARD_DAILYDETAILSSELL"]
    assert all('SECURITY_CODE="000636"' in c["filter"] for c in fake_http)


def test_fetch_lhb_assembles(fake_http):
    data = em.fetch_lhb(DAY, sleep=0)
    assert data["source"] == "eastmoney" and data["trade_date"] == DAY
    assert data["stock_count"] == 2 and data["note"] == ""
    first = data["items"][0]
    assert first["code"] == "000636" and first["reason"].startswith("日振幅值")
    assert first["buy_seats"][0]["name"] == "深股通专用"


def test_fetch_lhb_seat_error_tolerated(monkeypatch):
    def _fake(params, timeout=10.0, retries=2):
        rn = params["reportName"]
        if rn == "RPT_DAILYBILLBOARD_DETAILS":
            return LIST_PAYLOAD
        if "000636" in params["filter"]:
            raise em.EastmoneyError("超时")
        return BUY_PAYLOAD

    monkeypatch.setattr(em, "_get_json", _fake)
    import akshare as ak
    import pandas as pd
    monkeypatch.setattr(ak, "stock_lhb_jgmmtj_em",
                        lambda start_date, end_date: pd.DataFrame())
    data = em.fetch_lhb(DAY, sleep=0)
    assert data["stock_count"] == 2
    err_item = next(i for i in data["items"] if i["code"] == "000636")
    assert err_item["buy_seats"] == [] and "超时" in err_item["seat_error"]
    ok_item = next(i for i in data["items"] if i["code"] == "600664")
    assert ok_item["buy_seats"][0]["name"] == "深股通专用"
    assert "1 只个股席位拉取失败: 000636" in data["note"]


def test_fetch_lhb_empty_day_note(monkeypatch):
    monkeypatch.setattr(em, "_get_json",
                        lambda params, timeout=10.0, retries=2: EMPTY_PAYLOAD)
    import akshare as ak
    import pandas as pd
    monkeypatch.setattr(ak, "stock_lhb_jgmmtj_em",
                        lambda start_date, end_date: pd.DataFrame())
    data = em.fetch_lhb("2026-08-09", sleep=0)  # 周日
    assert data["stock_count"] == 0 and data["items"] == []
    assert "非交易日或披露未出" in data["note"]


def test_save_lhb_roundtrip(tmp_path, fake_http):
    path = em.save_lhb(em.fetch_lhb(DAY, sleep=0), tmp_path, DAY)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "2026-08-10.json"
    assert saved["stock_count"] == 2
    assert saved["items"][0]["buy_seats"][0]["net"] == 218964053.25


# ---------- C3 机构席位汇总（jgmmtj，2026-08-17 起） ----------


def _jgmmtj_df():
    import datetime as dt

    import pandas as pd
    return pd.DataFrame([
        {"序号": 1, "代码": "000636", "名称": "风华高科", "买方机构数": 2,
         "卖方机构数": 1, "机构买入总额": 1.2e8, "机构卖出总额": 3e7,
         "机构买入净额": 9e7, "机构净买额占总成交额比": 3.21,
         "上榜日期": dt.date(2026, 8, 10)},
        {"序号": 2, "代码": "600664", "名称": "哈药股份", "买方机构数": 0,
         "卖方机构数": 2, "机构买入总额": float("nan"), "机构卖出总额": 5e7,
         "机构买入净额": -5e7, "机构净买额占总成交额比": float("nan"),
         "上榜日期": dt.date(2026, 8, 10)},
    ])


@pytest.fixture
def fake_jgmmtj(monkeypatch):
    import akshare as ak
    monkeypatch.setattr(ak, "stock_lhb_jgmmtj_em",
                        lambda start_date, end_date: _jgmmtj_df())


def test_fetch_jgmmtj_parses(fake_jgmmtj):
    rows = em.fetch_jgmmtj(DAY)
    assert len(rows) == 2 and rows[0]["代码"] == "000636"
    assert rows[0]["机构买入净额"] == 9e7
    # NaN → None；date → ISO 字符串（json 可序列化）
    assert rows[1]["机构买入总额"] is None
    assert rows[1]["机构净买额占总成交额比"] is None
    assert rows[0]["上榜日期"] == "2026-08-10"
    json.dumps(rows)  # 不抛异常


def test_fetch_lhb_includes_jgmmtj(fake_http, fake_jgmmtj):
    data = em.fetch_lhb(DAY, sleep=0)
    assert isinstance(data["jgmmtj"], list) and len(data["jgmmtj"]) == 2
    assert data["jgmmtj"][0]["名称"] == "风华高科"
    assert data["note"] == ""


def test_fetch_lhb_jgmmtj_failure_tolerated(fake_http, monkeypatch):
    import akshare as ak

    def _boom(start_date, end_date):
        raise RuntimeError("akshare 被限流")

    monkeypatch.setattr(ak, "stock_lhb_jgmmtj_em", _boom)
    data = em.fetch_lhb(DAY, sleep=0)
    # 主流程不受影响，jgmmtj 置 None 并记 errors
    assert data["jgmmtj"] is None
    assert data["stock_count"] == 2
    assert "机构席位汇总" in data["note"] and "限流" in data["note"]


def test_save_lhb_idempotent_overwrite(tmp_path, fake_http, fake_jgmmtj):
    data = em.fetch_lhb(DAY, sleep=0)
    p1 = em.save_lhb(data, tmp_path, DAY)
    p2 = em.save_lhb(data, tmp_path, DAY)  # 重复保存覆盖同一路径
    assert p1 == p2
    saved = json.loads(p2.read_text(encoding="utf-8"))
    assert len(saved["jgmmtj"]) == 2
