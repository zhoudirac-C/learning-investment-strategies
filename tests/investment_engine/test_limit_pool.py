"""limit_pool.py 单元测试（monkeypatch _get_json，不触网）。"""

from __future__ import annotations

import json

import pytest

from investment_engine import limit_pool as lp

DAY = "20260811"


def _zt(code, name, lbc, fbt="93000", zbc=0, days=None, ct=None):
    return {"c": code, "n": name, "p": 10000, "zdp": 10.0, "amount": 1e8,
            "lbc": lbc, "fbt": fbt, "lbt": fbt, "fund": 5e7, "zbc": zbc,
            "hybk": "影视院线", "zttj": {"days": days or lbc, "ct": ct or lbc}}


def _zb(code, name):
    return {"c": code, "n": name, "p": 9000, "zdp": 3.0, "amount": 5e7,
            "zbc": 2, "hybk": "医药"}


@pytest.fixture
def fake_http(monkeypatch):
    def _fake(path, params, timeout=10.0, retries=2):
        if path == "/getTopicZTPool":
            return {"rc": 0, "data": {"tc": 4, "pool": [
                _zt("000802", "北京文化", 2, fbt="92500"),
                _zt("603758", "秦安股份", 3),
                _zt("600721", "百花医药", 5),
                _zt("002827", "高争民爆", 1),  # 昨日炸板今日涨停 → 反包
            ]}}
        if path == "/getTopicZBPool":
            return {"rc": 0, "data": {"tc": 1, "pool": [_zb("600000", "炸板股")]}}
        raise AssertionError(path)

    monkeypatch.setattr(lp, "_get_json", _fake)


def test_build_limit_pool_fields(fake_http, tmp_path):
    data = lp.build_limit_pool(DAY, tmp_path)
    assert data["zt_count"] == 4 and data["zb_count"] == 1
    assert data["max_lbc"] == 5
    assert list(data["ladder"].keys()) == ["5板", "3板", "2板"]
    assert data["auction_sealed"] == ["北京文化"]  # fbt=92500 且未炸板
    assert data["zt_items"][0]["days_ct"] == "2天2板"


def test_compare_with_prev_day(fake_http, tmp_path):
    # 前日落盘：2 只首板 + 炸板池含 002827
    prev = {"date": "2026-08-10",
            "zt_items": [{"code": "A", "lbc": 1}, {"code": "B", "lbc": 1},
                         {"code": "C", "lbc": 3}],
            "zb_items": [{"code": "002827", "name": "高争民爆"}]}
    (tmp_path / "20260810.json").write_text(json.dumps(prev), encoding="utf-8")
    data = lp.build_limit_pool(DAY, tmp_path, prev_day="20260810")
    cmp_ = data["compare"]
    assert cmp_["prev_first_board"] == 2 and cmp_["cur_lianban"] == 3
    assert cmp_["promotion_rate"] == 1.5
    assert cmp_["fanbao"] == ["高争民爆"]


def test_compare_missing_prev_annotated(fake_http, tmp_path):
    data = lp.build_limit_pool(DAY, tmp_path, prev_day="20260810")
    assert "未计算" in data["compare"]["note"]


def test_save_roundtrip(fake_http, tmp_path):
    path = lp.save_limit_pool(lp.build_limit_pool(DAY, tmp_path), tmp_path, DAY)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "20260811.json" and saved["max_lbc"] == 5
