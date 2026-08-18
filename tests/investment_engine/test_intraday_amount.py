"""intraday_amount.py 单元测试（注入 fake TDX，不触网）。"""
from __future__ import annotations

from investment_engine import intraday_amount as ia

DAY = "2026-08-17"   # 周一
PREV = "2026-08-14"  # 上周五
_HMS = ("10:30", "11:30", "14:00", "15:00")


def _bars(day: str, amounts: list[float]) -> list[dict]:
    return [{"datetime": f"{day} {hm}", "amount": a, "close": 1.0}
            for hm, a in zip(_HMS, amounts)]


class FakeTdx:
    """get_kline 按 code 返回预置 60min K 线（时间正序，与 pytdx 一致）。"""

    def __init__(self, sh: list[dict], sz: list[dict]):
        self._sh, self._sz = sh, sz

    def get_kline(self, code, category, count=16):
        assert category == "60min"
        return {"sh000001": self._sh, "sz399001": self._sz}[code]


def _flat_tdx() -> FakeTdx:
    # 每根两市各 1000 亿：累计 2000/4000/6000/8000，四点预估均 8000 → 平量
    sh = _bars(PREV, [1e11] * 4) + _bars(DAY, [1e11] * 4)
    sz = _bars(PREV, [1e11] * 4) + _bars(DAY, [1e11] * 4)
    return FakeTdx(sh, sz)


def test_compute_keys_and_flat_shape():
    data = ia.compute_intraday_amount(tdx=_flat_tdx())
    # 键名与 dataset._load_intraday_amount 产出完全一致（prompt 规则 9 引用）
    assert set(data) == {"date", "分时", "开盘预估全天_亿", "尾盘实际全天_亿", "形态"}
    assert data["date"] == DAY  # 由最新一根 K 线推导，前一交易日 K 线被滤掉
    assert len(data["分时"]) == 4
    assert [set(r) for r in data["分时"]] == [{"时点", "累计_亿", "预估全天_亿"}] * 4
    assert [r["时点"] for r in data["分时"]] == list(_HMS)
    assert [r["累计_亿"] for r in data["分时"]] == [2000, 4000, 6000, 8000]
    # 预估全天 = 累计 × 240/已交易分钟
    assert [r["预估全天_亿"] for r in data["分时"]] == [8000, 8000, 8000, 8000]
    assert data["开盘预估全天_亿"] == 8000
    assert data["尾盘实际全天_亿"] == 8000
    assert data["形态"] == "平量"


def test_shape_spike_fade():
    # 首根 1 万亿（开盘预估 4 万亿），后三根各 100 亿 → 冲量滑落
    sh = _bars(DAY, [1e12, 1e10, 1e10, 1e10])
    sz = _bars(DAY, [0.0] * 4)
    data = ia.compute_intraday_amount(tdx=FakeTdx(sh, sz))
    assert data["开盘预估全天_亿"] == 40000
    assert data["尾盘实际全天_亿"] == 10300
    assert data["形态"] == "冲量滑落（全天缩量）"


def test_shape_step_up():
    # 首根仅 100 亿，后三根各 1000 亿 → 逐级放大
    sh = _bars(DAY, [1e10, 1e11, 1e11, 1e11])
    sz = _bars(DAY, [0.0] * 4)
    data = ia.compute_intraday_amount(tdx=FakeTdx(sh, sz))
    assert data["开盘预估全天_亿"] == 400
    assert data["尾盘实际全天_亿"] == 3100
    assert data["形态"] == "逐级放大（健康放量）"


def test_tdx_unavailable_returns_none():
    class BoomTdx:
        def get_kline(self, *a, **kw):
            raise ConnectionError("tdx refused")

    assert ia.compute_intraday_amount(tdx=BoomTdx()) is None
    assert ia.compute_intraday_amount(tdx=FakeTdx([], [])) is None


def test_insufficient_day_bars_returns_none():
    # 当日只有 3 根（盘中 14:00 前）→ 数据不足
    sh = _bars(DAY, [1e11] * 3)
    sz = _bars(DAY, [1e11] * 3)
    assert ia.compute_intraday_amount(tdx=FakeTdx(sh, sz)) is None


def test_save_load_roundtrip(tmp_path):
    data = ia.compute_intraday_amount(tdx=_flat_tdx())
    path = ia.save_intraday_amount(DAY, data, tmp_path)
    assert path.name == "20260817.json"
    loaded = ia.load_intraday_amount(DAY, tmp_path)
    assert loaded == data
    assert ia.load_intraday_amount("2026-08-18", tmp_path) is None
