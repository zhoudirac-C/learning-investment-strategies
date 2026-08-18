"""fund_flow.py 单元测试（monkeypatch akshare，不触网）。"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from investment_engine import fund_flow as ff


def _df(name: str, net: float | None) -> pd.DataFrame:
    return pd.DataFrame({
        "序号": [1, 2],
        "名称": [name, "卧龙岗"],
        "今日主力净流入-净额": [net, -2.5e8],
        "领涨股": ["贵州茅台", "平安银行"],
    })


@pytest.fixture
def fake_ak(monkeypatch):
    """行业/概念全窗口返回 2 行假数据。"""
    import akshare as ak
    monkeypatch.setattr(ak, "stock_fund_flow_industry",
                        lambda symbol: _df(f"白酒{symbol}", 1.5e9))
    monkeypatch.setattr(ak, "stock_fund_flow_concept",
                        lambda symbol: _df(f"算力{symbol}", 3.0e8))
    # 测试不走真实网络，去掉窗口间节流
    monkeypatch.setattr(ff, "REQUEST_INTERVAL", 0)


def test_fetch_fund_flow_shape(fake_ak):
    payload = ff.fetch_fund_flow()
    assert set(payload) == {"date", "fetched_at", "industry", "concept", "errors"}
    assert payload["errors"] == []
    for kind in ("industry", "concept"):
        assert set(payload[kind]) == set(ff.WINDOWS)
        rows = payload[kind]["即时"]
        assert len(rows) == 2
        assert rows[0]["名称"].startswith(("白酒", "算力"))
        assert rows[0]["今日主力净流入-净额"] > 0
    assert payload["industry"]["3日排行"][0]["名称"] == "白酒3日排行"


def test_nan_becomes_none(fake_ak, monkeypatch):
    import akshare as ak
    df = _df("白酒即时", None)  # 首行净额为 NaN
    monkeypatch.setattr(ak, "stock_fund_flow_industry", lambda symbol: df)
    payload = ff.fetch_fund_flow()
    assert payload["industry"]["即时"][0]["今日主力净流入-净额"] is None
    assert payload["industry"]["即时"][1]["今日主力净流入-净额"] == -2.5e8


def test_single_window_failure_tolerated(fake_ak, monkeypatch):
    import akshare as ak

    def _boom(symbol):
        if symbol == "3日排行":
            raise RuntimeError("RemoteDisconnected")
        return _df(f"白酒{symbol}", 1.5e9)

    monkeypatch.setattr(ak, "stock_fund_flow_industry", _boom)
    payload = ff.fetch_fund_flow()
    assert payload["industry"]["3日排行"] is None  # 失败窗口记 None
    assert len(payload["errors"]) == 1
    assert "industry/3日排行" in payload["errors"][0]
    # 其余窗口与概念全部不受影响
    assert len(payload["industry"]["即时"]) == 2
    assert len(payload["concept"]["10日排行"]) == 2


def test_save_fund_flow_filename(fake_ak, tmp_path):
    payload = ff.fetch_fund_flow()
    payload["date"] = "2026-08-17"
    path = ff.save_fund_flow(payload, tmp_path)
    assert path.name == "20260817.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["date"] == "2026-08-17"
    assert saved["concept"]["5日排行"][0]["名称"] == "算力5日排行"
