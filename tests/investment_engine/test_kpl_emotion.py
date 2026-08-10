"""kpl/emotion.py 单元测试（实样裁剪自 2026-08-10 盘中抓包）。"""

from __future__ import annotations

import json

from investment_engine.kpl.emotion import fetch_snapshot, save_snapshot

# 真实响应裁剪：注意 FKYDSixList 是 object 列表、CWeatherVaneList 是 {SZ,XD}、
# 本样例无 ErBanList（验证缺块容忍）。errcode 已被 client 层消费，这里模拟 client 返回。
SAMPLE = {
    "BaceFaceList": [["医药", "0.96", 801045], ["并购重组", "0.44", 801250]],
    "FKYDSixList": [{"StockID": "300654", "StockName": "世纪天鸿", "zhangfu": "3.54%"}],
    "DaBanList": {"tZhangTing": 76, "lZhangTing": 74, "tFengBan": 85.3933,
                  "tDieTing": 5, "SZJS": 3470, "XDJS": 1965, "PPJS": 103,
                  "ZHQD": 60, "ZRZTJ": 0.294, "ZRLBJ": -0.532},
    "CWeatherVaneList": {"SZ": [["001258", "立新能源", 10.03, "绿色电力"]],
                         "XD": [["301251", "威尔高", -9.42, "印制电路板"]]},
    "PHBList": [["600721", "百花医药", 9.96, 1, "5连板", "医药", "医药;2|5连板;1"]],
    "Day": "2026-08-10",
    "errcode": "0",
}


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, subdomain, c, a, params=None):
        self.calls.append((subdomain, c, a, params))
        return self.payload


def test_fetch_snapshot_blocks_and_view():
    client = _FakeClient(SAMPLE)
    data = fetch_snapshot(client)
    # 全量 View 一次拉取
    assert client.calls == [("apphwhq", "Index", "GetInfo",
                             {"View": "2,3,4,5,7,8,9,10,11"})]
    assert data["date"] == "2026-08-10"
    assert data["fetched_at"]
    assert data["daban"]["tZhangTing"] == 76
    assert data["daban"]["tFengBan"] == 85.3933
    assert data["lianban"][0][4] == "5连板"
    assert data["erban"] == []  # 缺块给空列表
    assert data["fengkou"][0]["StockID"] == "300654"  # object 列表原样保留
    assert data["bankuai"][0] == ["医药", "0.96", 801045]
    assert data["fengxiang"]["SZ"][0][1] == "立新能源"  # {SZ,XD} 原样保留


def test_save_snapshot(tmp_path):
    data = {"date": "2026-08-10", "fetched_at": "2026-08-10T15:45:02",
            "daban": {"tZhangTing": 76}, "lianban": [], "erban": [],
            "fengkou": [], "bankuai": [], "fengxiang": {}}
    path = save_snapshot(data, tmp_path, "2026-08-10")
    assert path == tmp_path / "emotion" / "2026-08-10.json"
    loaded = json.loads(path.read_text())
    assert loaded == data  # 完整往返；ensure_ascii=False 中文不转义
