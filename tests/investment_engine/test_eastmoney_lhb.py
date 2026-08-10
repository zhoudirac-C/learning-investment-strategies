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
    data = em.fetch_lhb("2026-08-09", sleep=0)  # 周日
    assert data["stock_count"] == 0 and data["items"] == []
    assert "非交易日或披露未出" in data["note"]


def test_save_lhb_roundtrip(tmp_path, fake_http):
    path = em.save_lhb(em.fetch_lhb(DAY, sleep=0), tmp_path, DAY)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "2026-08-10.json"
    assert saved["stock_count"] == 2
    assert saved["items"][0]["buy_seats"][0]["net"] == 218964053.25
