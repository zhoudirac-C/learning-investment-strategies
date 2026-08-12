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
    # 保持测试密闭：监管距离特征不触真实 K 线缓存、不触网
    import investment_engine.backtest.history as hist
    monkeypatch.setattr(hist, "get_klines_range", lambda *a, **k: [])
    import qing_investment.agent.tools.stock_data as sd
    monkeypatch.setattr(sd, "fetch_stock_kline", lambda *a, **k: [])


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


# ---------- P1 特征（2026-08-12 起） ----------

def test_first_board_width_no_history(fake_http, tmp_path):
    data = lp.build_limit_pool(DAY, tmp_path)
    fbw = data["first_board_width"]
    assert fbw["count"] == 1  # 仅高争民爆 lbc=1
    assert fbw["dod_delta"] is None and fbw["pctile_20d"] is None
    assert "无历史落盘" in fbw["note"]


def test_first_board_width_with_history(fake_http, tmp_path):
    prev = {"date": "2026-08-10",
            "zt_items": [{"code": "A", "lbc": 1}, {"code": "B", "lbc": 1},
                         {"code": "C", "lbc": 3}]}
    (tmp_path / "20260810.json").write_text(json.dumps(prev), encoding="utf-8")
    data = lp.build_limit_pool(DAY, tmp_path)
    fbw = data["first_board_width"]
    assert fbw["count"] == 1 and fbw["prev_date"] == "20260810"
    assert fbw["dod_delta"] == -1  # 1 - 2
    assert fbw["pctile_20d"] == 0.0  # 窗口=[2]，"历史值 ≤ 今日值(1)" 0 天 → 0.0
    assert fbw["sample_days"] == 1 and "<20" in fbw["note"]


def _fake_bars(code, start, end, **kw):
    # 31 个交易日：个股每日 +5%，指数每日 +1% → 日偏离 4 个百分点
    closes = [100.0 * (1.05 ** i) for i in range(31)]
    idx_closes = [1000.0 * (1.01 ** i) for i in range(31)]
    series = closes if code == "600721" else idx_closes
    return [{"trade_date": f"2026-07-{i + 1:02d}", "close": c}
            for i, c in enumerate(series)]


def test_regulatory_distance_fabricated(fake_http, monkeypatch):
    import investment_engine.backtest.history as hist
    monkeypatch.setattr(hist, "get_klines_range", _fake_bars)
    data = lp.build_limit_pool(DAY, None)
    rd = data["regulatory_distance"]
    assert rd["leader_code"] == "600721" and rd["leader_lbc"] == 5
    assert rd["index_proxy"] == "IDX000001"
    assert rd["dev_10d"] == pytest.approx(40.0, abs=0.01)
    assert rd["dist_10d"] == pytest.approx(60.0, abs=0.01)
    assert rd["dev_30d"] == pytest.approx(120.0, abs=0.01)
    assert rd["dist_30d"] == pytest.approx(80.0, abs=0.01)


def test_regulatory_distance_kline_missing(fake_http, tmp_path):
    # fixture 已把 get_klines_range 置为返回空 → 如实标注而非报错
    data = lp.build_limit_pool(DAY, tmp_path)
    rd = data["regulatory_distance"]
    assert rd["leader_code"] == "600721" and "不足" in rd["note"]
