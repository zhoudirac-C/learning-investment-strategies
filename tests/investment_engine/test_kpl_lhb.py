"""kpl/lhb.py 单元测试（结构依接口清单第 5 节文档；响应体压缩未能离线还原实样）。"""

from __future__ import annotations

import json

from investment_engine.kpl.lhb import fetch_lhb, save_lhb

SAMPLE = {
    "errcode": "0",
    "Day": "2026-08-10",
    "NDay": "2026-08-07",
    "TList": [["1", "顶级游资"], ["4", "机构"]],
    "List": [{"StockID": "600664", "StockName": "哈药股份", "TypeName": "一线游资"}],
}
EMPTY = {"errcode": "0", "Day": "2026-08-07", "NDay": "2026-08-06",
         "TList": [["1", "顶级游资"]], "List": []}


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, subdomain, c, a, params=None):
        self.calls.append((subdomain, c, a, params))
        return self.payload


def test_fetch_lhb_fields():
    client = _FakeClient(SAMPLE)
    data = fetch_lhb(client)
    assert client.calls == [("applhb", "UserBusiness", "GetDay", None)]
    assert data["disclosure_day"] == "2026-08-10"
    assert data["prev_disclosure_day"] == "2026-08-07"
    assert data["tlist"] == [["1", "顶级游资"], ["4", "机构"]]
    assert len(data["list"]) == 1 and data["note"] == ""


def test_fetch_lhb_empty_list_tolerated():
    data = fetch_lhb(_FakeClient(EMPTY))
    assert data["list"] == [] and "非披露日" in data["note"]


def test_save_lhb(tmp_path):
    path = save_lhb(fetch_lhb(_FakeClient(SAMPLE)), tmp_path, "2026-08-10")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "2026-08-10.json"
    assert saved["list"][0]["StockID"] == "600664"
