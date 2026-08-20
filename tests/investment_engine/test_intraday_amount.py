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
    # 「形态」等旧键名不动（prompt 规则 9 引用）；校准新增字段并列呈现
    assert set(data) == {"date", "分时", "开盘预估全天_亿", "尾盘实际全天_亿", "形态",
                         "环比前日_pct", "占比中位数", "校准残差_pct"}
    assert data["date"] == DAY  # 由最新一根 K 线推导，前一交易日 K 线被滤掉
    assert len(data["分时"]) == 4
    assert [set(r) for r in data["分时"]] == [{"时点", "累计_亿", "预估全天_亿"}] * 4
    assert [r["时点"] for r in data["分时"]] == list(_HMS)
    assert [r["累计_亿"] for r in data["分时"]] == [2000, 4000, 6000, 8000]
    # 预估全天 = 累计 ÷ 历史同时段占比中位数（前日为平量日 → 占比 25/50/75/100%）
    assert [r["预估全天_亿"] for r in data["分时"]] == [8000, 8000, 8000, 8000]
    assert data["开盘预估全天_亿"] == 8000
    assert data["尾盘实际全天_亿"] == 8000
    assert data["形态"] == "平量"
    assert data["环比前日_pct"] == 0.0
    assert data["占比中位数"] == {"10:30": 0.25, "11:30": 0.5, "14:00": 0.75, "15:00": 1.0}
    assert data["校准残差_pct"] == 0.0


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


def _bars_from_cum(day: str, cums: list[float]) -> list[dict]:
    """按四点累计（亿）反推每根 60min bar 的 amount（元）。"""
    amounts, prev = [], 0.0
    for c in cums:
        amounts.append((c - prev) * 1e8)
        prev = c
    return _bars(day, amounts)


def test_calibrated_est_realistic_distribution():
    """08-19 回归：首小时占比 ~48% 的真实分布下不得再误判「冲量滑落」。"""
    prev = _bars_from_cum(PREV, [11520, 15360, 19200, 24000])   # 占比 48/64/80/100%
    today = _bars_from_cum(DAY, [12125, 16181, 20132, 25110])   # 08-19 实际曲线
    tdx = FakeTdx(prev + today, [dict(b, amount=0.0) for b in prev + today])
    data = ia.compute_intraday_amount(tdx=tdx)
    # 校准预估 ≈ 实际（旧 ×4 模型给 48501，偏差 93%）
    assert [r["预估全天_亿"] for r in data["分时"]] == [25260, 25283, 25165, 25110]
    assert data["尾盘实际全天_亿"] == 25110
    assert data["形态"] == "平量"           # 旧模型误判「冲量滑落（全天缩量）」
    assert data["环比前日_pct"] == 4.6      # 25110 vs 24000：放量，与 UP 判定一致
    assert data["占比中位数"]["10:30"] == 0.48
    assert data["校准残差_pct"] == 0.0      # 单日样本自洽


def test_residual_and_ratio_medians_over_history():
    """残差 = 各历史日「10:30 校准预估 / 当日实际 - 1」绝对偏差的中位数。"""
    d1 = _bars_from_cum("2026-08-13", [11520, 15360, 19200, 24000])  # 10:30 占比 .48
    d2 = _bars_from_cum(PREV, [11900, 15470, 19040, 23800])          # 10:30 占比 .50
    today = _bars_from_cum(DAY, [12250, 16300, 20400, 25500])
    tdx = FakeTdx(d1 + d2 + today, [dict(b, amount=0.0) for b in d1 + d2 + today])
    data = ia.compute_intraday_amount(tdx=tdx)
    assert data["占比中位数"]["10:30"] == 0.49      # (.48 + .50) / 2
    # 两日偏差 ±2.04% 对称 → 中位 2.0
    assert data["校准残差_pct"] == 2.0
    assert data["开盘预估全天_亿"] == 25000         # 12250 / 0.49
    assert data["环比前日_pct"] == 7.1              # 25500 vs 23800


def test_day_param_backfills_without_leakage():
    """指定历史日重算：校准只能用该日之前的样本，之后的数据不得泄漏。"""
    d1 = _bars_from_cum("2026-08-17", [10000, 14000, 17000, 20000])  # 10:30 占比 .50
    d2 = _bars_from_cum("2026-08-18", [10000, 14000, 17000, 22000])
    d3 = _bars_from_cum("2026-08-19", [19800, 21000, 21500, 22000])  # 10:30 占比 .90
    tdx = FakeTdx(d1 + d2 + d3, [dict(b, amount=0.0) for b in d1 + d2 + d3])
    data = ia.compute_intraday_amount(tdx=tdx, day="2026-08-18")
    assert data["date"] == "2026-08-18"
    # 仅用 08-17 校准：10000 / 0.5 = 20000；若混入 .90 则得 ~14000
    assert data["开盘预估全天_亿"] == 20000
    assert data["占比中位数"]["10:30"] == 0.5
    assert data["环比前日_pct"] == 10.0             # 22000 vs 20000


def test_naive_fallback_without_history():
    """无历史日（单日数据）时回退 ×240/分钟 朴素外推，校准字段为 None。"""
    sh = _bars(DAY, [1e12, 1e10, 1e10, 1e10])
    sz = _bars(DAY, [0.0] * 4)
    data = ia.compute_intraday_amount(tdx=FakeTdx(sh, sz))
    assert data["开盘预估全天_亿"] == 40000         # 10000 × 240/60
    assert data["形态"] == "冲量滑落（全天缩量）"
    assert data["占比中位数"] is None
    assert data["校准残差_pct"] is None
    assert data["环比前日_pct"] is None
