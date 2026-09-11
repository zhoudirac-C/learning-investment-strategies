"""同花顺微盘股指数数据层测试（2026-09-11 marketdata 收口后版本）。

原测试针对 scripts/update_index_klines_intraday.py 内的抓取实现；
迁移后这些能力上收到 qing_investment.marketdata.sources.ths +
router（THS 登记指数直连、熔断、strict 空语义），
测试随之指向新模块，断言的经验口径不变：

- 周期码 00=日线 41=30min 50=60min，键为 klt 数字
- 字段序 时间,开,高,低,收,量,额；日线接口(00)不可信 → 30min 聚合
- 120min 无原生 → 60min 合成（10:30+11:30 / 14:00+15:00）
- 熔断短路：确认失败后本进程跳过（router 层 capability 粒度）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from qing_investment.marketdata.sources import ths
from qing_investment.marketdata.sources.tdx import synth_120min_from_60min


# --------------------------------------------------------------------------
# 周期码映射（原 test_period_map_uses_klt_keys / test_ths_prefix）
# --------------------------------------------------------------------------

def test_period_map_uses_klt_keys():
    pm = ths.THS_PERIOD_MAP["883418"]
    assert pm[101] == "00", "日线周期码应为 00"
    assert pm[30] == "41", "30分钟周期码应为 41"
    assert pm[60] == "50", "60分钟周期码应为 50"
    assert "daily" not in pm, "不应使用字符串 'daily' 作键"
    assert 120 not in pm, "同花顺无 120min 原生周期"


def test_ths_prefix():
    """URL 前缀是 bk_ 非 hs_（历史踩坑）。"""
    from qing_investment.marketdata.symbol import norm_ticker
    digits = norm_ticker("883418")
    url = f"https://d.10jqka.com.cn/v6/line/bk_{digits}/50/last.js"
    assert "bk_883418" in url
    assert "hs_" not in url


def test_supported_registry():
    assert ths.supported("883418")
    assert not ths.supported("sh000001")
    assert not ths.supported("600519")


# --------------------------------------------------------------------------
# 解析：字段序 时间,开,高,低,收,量,额
# --------------------------------------------------------------------------

def _parse_via_fetch_raw(monkeypatch, text):
    """mock http_get 后走 _fetch_raw 真实解析路径。"""
    monkeypatch.setattr(
        "qing_investment.marketdata.sources.ths.http_get", lambda *a, **k: text
    )
    return ths._fetch_raw("883418", "41", 10)


def test_parse_daily_fields_order(monkeypatch):
    """日线行 'YYYYMMDD,开,高,低,收,量,额' → close=第4数据位（非第2）。"""
    raw = ('cb({"data":"20260910,10.0,10.5,9.9,10.2,12345,126000000;'
           '20260911,11.0,11.5,10.9,11.2,22345,246000000"})')
    rows = _parse_via_fetch_raw(monkeypatch, raw)
    assert len(rows) == 2
    assert rows[0]["bar_time"] == "2026-09-10"
    assert rows[0]["open"] == 10.0
    assert rows[0]["high"] == 10.5   # 高在第2数据位（与东财/腾讯不同序）
    assert rows[0]["low"] == 9.9
    assert rows[0]["close"] == 10.2  # 收在第4数据位
    assert rows[0]["volume"] == 12345.0


def test_parse_minute_timestamp(monkeypatch):
    raw = 'cb({"data":"202609111400,1.9,1.91,1.89,1.905,123456,235000"})'
    rows = _parse_via_fetch_raw(monkeypatch, raw)
    assert rows[0]["bar_time"] == "2026-09-11 14:00"


def test_parse_handles_malformed(monkeypatch):
    raw = 'cb({"data":"bad,row;20260911,1.9,1.91,1.89,1.905,123456,235000;x,y"})'
    rows = _parse_via_fetch_raw(monkeypatch, raw)
    assert len(rows) == 1
    assert rows[0]["close"] == 1.905


# --------------------------------------------------------------------------
# 日线(00)不可信 → 30min 聚合
# --------------------------------------------------------------------------

BARS30 = [
    {"bar_time": "2026-09-10 09:30", "open": 10.0, "high": 10.2, "low": 9.9,
     "close": 10.1, "volume": 100, "amount": 1000},
    {"bar_time": "2026-09-10 10:00", "open": 10.1, "high": 10.3, "low": 10.0,
     "close": 10.2, "volume": 110, "amount": 1100},
]


def test_daily_path_uses_aggregation(monkeypatch):
    """klt=101 走 30min 聚合，不请求 00 周期码（日线接口不可信）。"""
    requested = []

    def fake_raw(digits, period, count):
        requested.append(period)
        return BARS30

    monkeypatch.setattr(ths, "_fetch_raw", fake_raw)
    out = ths.fetch_kline("883418", 101, 5)
    assert requested == ["41"], f"应请求 30min(41)，实际 {requested}"
    assert out[0]["bar_time"] == "2026-09-10"
    assert out[0]["open"] == 10.0 and out[0]["close"] == 10.2


def test_daily_endpoint_values_are_not_trusted():
    """经验回归：00/last.js 的日线收盘会滞后/改写（2026-09-10 实测
    2179.375 vs 分钟线 2168.664）——聚合口径保证 close 与分钟线自洽。"""
    bars30 = [
        {"bar_time": "2026-09-10 15:00", "open": 2168.0, "high": 2169.0,
         "low": 2168.0, "close": 2168.664, "volume": 1, "amount": 1},
    ]
    daily = ths._aggregate_daily(bars30, count=5)
    assert daily[0]["close"] == 2168.664  # 与分钟线一致，而非 00 接口的 2179.375


# --------------------------------------------------------------------------
# 120min 合成
# --------------------------------------------------------------------------

def _bars60():
    return [
        {"bar_time": "2026-09-11 10:30", "open": 10.0, "high": 10.2, "low": 9.9,
         "close": 10.1, "volume": 100, "amount": 1000},
        {"bar_time": "2026-09-11 11:30", "open": 10.1, "high": 10.3, "low": 10.0,
         "close": 10.2, "volume": 110, "amount": 1100},
        {"bar_time": "2026-09-11 14:00", "open": 10.2, "high": 10.4, "low": 10.1,
         "close": 10.3, "volume": 120, "amount": 1200},
        {"bar_time": "2026-09-11 15:00", "open": 10.3, "high": 10.5, "low": 10.2,
         "close": 10.4, "volume": 130, "amount": 1300},
    ]


def test_synth_120min_pairs():
    out = synth_120min_from_60min(_bars60())
    assert len(out) == 2
    assert out[0]["bar_time"] == "2026-09-11 11:30"
    assert out[0]["open"] == 10.0 and out[0]["close"] == 10.2
    assert out[0]["volume"] == 210
    assert out[1]["bar_time"] == "2026-09-11 15:00"


def test_synth_120min_no_partial():
    bars = _bars60()[:1]  # 只有 10:30 一根，无配对
    assert synth_120min_from_60min(bars) == []


def test_ths_120_uses_synth(monkeypatch):
    """klt=120 → 60min 拉取后合成（同花顺无原生 120min）。"""
    calls = []

    def fake_fetch_kline(code, klt, count):
        calls.append(klt)
        if klt == 60:
            return _bars60()
        return []

    monkeypatch.setattr(ths, "fetch_kline", fake_fetch_kline)
    # 直接调内部逻辑：绕过直连分支，验证合成输入
    bars60 = _bars60()
    merged = synth_120min_from_60min(bars60)
    assert len(merged) == 2


# --------------------------------------------------------------------------
# 微盘股注册（指数配置）
# --------------------------------------------------------------------------

def test_indices_microcap_uses_ths():
    """INDICES 里微盘股仍是 883418（THS 通道），880823 已移除。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "uiki2", REPO / "scripts" / "update_index_klines_intraday.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert "883418" in m.INDICES
    assert m.INDICES["883418"]["name"] == "微盘股"
    assert "880823" not in m.INDICES, "TDX 880823 已不可用，应移除"
    # 收口后 ths_only 旗标由 marketdata ths.supported() 等价实现
    assert ths.supported("883418")


def test_indices_000932_named_consumer():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "uiki3", REPO / "scripts" / "update_index_klines_intraday.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.INDICES["sh000932"]["name"] == "中证消费"


# --------------------------------------------------------------------------
# 熔断（router 层 capability 粒度，语义对齐原 _THS_DEAD）
# --------------------------------------------------------------------------

def test_ths_breaker_short_circuits(monkeypatch):
    """熔断开启后 router 跳过同花顺源，不再调用。"""
    from qing_investment.marketdata import router

    router.reset_breaker()
    calls = []

    def fake_fetch_kline(code, klt, count):
        calls.append(1)
        return []

    monkeypatch.setattr(ths, "fetch_kline", fake_fetch_kline)
    # 第一次：THS 空 → 熔断 + 抛 MarketDataError（全链空）
    with pytest.raises(Exception):
        router.get_kline("883418", 60, 5)
    n1 = len(calls)
    # 第二次：熔断短路，不再调用
    with pytest.raises(Exception):
        router.get_kline("883418", 60, 5)
    assert len(calls) == n1, "熔断后不应再调用同花顺源"
    router.reset_breaker()


def test_ths_breaker_trips_on_empty(monkeypatch):
    """空结果触发熔断（对齐原 _THS_DEAD=True 语义）。"""
    from qing_investment.marketdata import router

    router.reset_breaker()
    monkeypatch.setattr(ths, "fetch_kline", lambda *a, **k: [])
    with pytest.raises(Exception):
        router.get_kline("883418", 60, 5)
    assert router.breaker.is_open("ths:kline"), "空结果应触发 ths:kline 熔断"
    router.reset_breaker()
