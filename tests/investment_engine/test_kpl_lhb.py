"""kpl/lhb.py 单元测试（结构已按 2026-08-11 实测响应修正：List 为分类分组 dict）。"""

from __future__ import annotations

import json

from investment_engine.kpl.lhb import fetch_lhb, save_lhb

SAMPLE = {
    "errcode": "0",
    "Day": "2026-08-10",
    "NDay": "2026-08-07",
    "TList": [{"ID": 3, "Name": "顶级游资"}, {"ID": 2, "Name": "一线游资"}],
    "List": {"3": [], "2": [{"StockID": "600664", "StockName": "哈药股份"}],
             "4": [], "5": [], "1": [], "6": []},
}
EMPTY = {"errcode": "0", "Day": "2026-08-07", "NDay": "2026-08-06",
         "TList": [{"ID": 3, "Name": "顶级游资"}],
         "List": {"3": [], "2": [], "4": [], "5": [], "1": [], "6": []}}


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
    assert data["tlist"] == [{"ID": 3, "Name": "顶级游资"}, {"ID": 2, "Name": "一线游资"}]
    assert data["entry_count"] == 1 and data["note"] == ""


def test_fetch_lhb_empty_dict_tolerated():
    # 空明细时 List 仍带 6 个分类键，entry_count 必须为 0 且 note 标注
    data = fetch_lhb(_FakeClient(EMPTY))
    assert data["entry_count"] == 0 and "明细为空" in data["note"]


def test_fetch_lhb_day_param_backfill():
    client = _FakeClient(SAMPLE)
    fetch_lhb(client, "2026-08-07")
    assert client.calls == [("applhb", "UserBusiness", "GetDay", {"Day": "2026-08-07"})]


def test_save_lhb(tmp_path):
    path = save_lhb(fetch_lhb(_FakeClient(SAMPLE)), tmp_path, "2026-08-10")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "2026-08-10.json"
    assert saved["list"]["2"][0]["StockID"] == "600664"
    assert saved["entry_count"] == 1
