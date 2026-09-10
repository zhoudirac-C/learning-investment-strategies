"""同花顺微盘股指数 (883418) 数据源回归测试。

背景 (2026-09-10)：TDX 常规 K线接口被服务端按接口粒度封禁，
原微盘股指数 (TDX 880823) 失去数据。改用同花顺 883418「微盘股」——
与万得微盘股同口径（沪深A股市值最小 400 只等权）。

本测试锁定：
1. 周期码映射正确（101→00 日线, 30→41, 60→50）
2. 120min 无原生周期 → 由 60min 合成
3. 时间戳格式解析（8位日线 / 12位分钟线）
4. 字段顺序正确（同花顺是 时间,开,高,低,收 —— 与东财 时间,开,收,高,低 不同！）
5. 熔断标志生效

离线可跑（不碰网络）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))


def _load_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "uiki", REPO / "scripts" / "update_index_klines_intraday.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def mod():
    return _load_mod()


# --------------------------------------------------------------------------
# 周期码映射
# --------------------------------------------------------------------------

def test_period_map_uses_klt_keys(mod):
    """键必须是 TIMEFRAMES 的 klt 数字（101=日线），不是 'daily' 字符串。

    历史 bug：最初写成 {"daily": "00"} → fetch 永远返回 []。
    """
    pm = mod._THS_PERIOD_MAP["883418"]
    assert pm[101] == "00", "日线周期码应为 00"
    assert pm[30] == "41", "30分钟周期码应为 41"
    assert pm[60] == "50", "60分钟周期码应为 50"
    assert "daily" not in pm, "不应使用字符串 'daily' 作键"
    # 同花顺无 120min 原生周期
    assert 120 not in pm


def test_ths_prefix(mod):
    assert mod._THS_PREFIX == "bk_"


# --------------------------------------------------------------------------
# 解析：字段顺序 + 时间格式
# --------------------------------------------------------------------------

def test_parse_daily_fields_order(mod):
    """同花顺字段顺序是 时间,开,高,低,收 —— 与东财 (时间,开,收,高,低) 不同。

    若照抄东财解析器，high/low/close 会全部错位。
    """
    raw = ["20260910,2186.112,2186.112,2161.042,2167.324,1114109220,10978902200.000,,,0"]
    rows = mod._parse_ths_klines(raw)
    assert len(rows) == 1
    r = rows[0]
    assert r["bar_time"] == "2026-09-10"
    assert r["open"] == pytest.approx(2186.112)
    assert r["high"] == pytest.approx(2186.112)
    assert r["low"] == pytest.approx(2161.042)
    assert r["close"] == pytest.approx(2167.324), "close 必须取第 5 列(索引4)"


def test_synth_daily_from_intraday(mod, monkeypatch):
    """日线必须由 30min 聚合，不能直接信同花顺 00 接口。

    2026-09-10 实测：00/last.js=2179.375、00/2026.js=2167.324、
    而 30min/60min/分时/官网 一致为 2168.664。故日线走聚合。
    """
    fake_30min = [
        {"bar_time": "2026-09-10 10:00", "open": 2186.112, "high": 2186.112,
         "low": 2161.042, "close": 2165.287, "volume": 100.0, "amount": 1000.0},
        {"bar_time": "2026-09-10 10:30", "open": 2164.890, "high": 2166.580,
         "low": 2157.543, "close": 2160.137, "volume": 50.0, "amount": 500.0},
        {"bar_time": "2026-09-10 15:00", "open": 2173.677, "high": 2173.793,
         "low": 2166.574, "close": 2168.664, "volume": 70.0, "amount": 700.0},
        # 前一日
        {"bar_time": "2026-09-09 15:00", "open": 2214.0, "high": 2215.147,
         "low": 2189.972, "close": 2194.988, "volume": 20.0, "amount": 200.0},
    ]
    monkeypatch.setattr(mod, "fetch_latest_klines_from_ths",
                        lambda code, klt, count=5: fake_30min if klt == 30 else [])
    out = mod._synth_daily_from_intraday("883418", 5)
    assert len(out) == 2, "两个自然日应聚成 2 根日线"
    d10 = [b for b in out if b["bar_time"] == "2026-09-10"][0]
    assert d10["open"] == pytest.approx(2186.112), "开盘取当日首根"
    assert d10["close"] == pytest.approx(2168.664), "收盘取当日末根（权威值）"
    assert d10["high"] == pytest.approx(2186.112)
    assert d10["low"] == pytest.approx(2157.543)
    assert d10["volume"] == pytest.approx(220.0), "成交量求和"
    assert out[0]["bar_time"] == "2026-09-09", "按日期升序"


def test_daily_path_uses_aggregation(mod, monkeypatch):
    """klt=101 走聚合，不走 00 接口。"""
    monkeypatch.setattr(mod, "_THS_DEAD", False)
    called = {"agg": 0, "raw": 0}

    def _agg(code, count):
        called["agg"] += 1
        return [{"bar_time": "2026-09-10", "open": 1.0, "high": 2.0,
                 "low": 0.5, "close": 1.5, "volume": 1.0, "amount": 1.0}]

    def _raw(code, klt, count=5):
        called["raw"] += 1
        return []

    monkeypatch.setattr(mod, "_synth_daily_from_intraday", _agg)
    monkeypatch.setattr(mod, "fetch_latest_klines_from_ths", _raw)
    out = mod._fetch_ths_with_breaker("883418", 101, 5)
    assert called["agg"] == 1, "日线应走聚合"
    assert called["raw"] == 0, "日线不应直接取 00 接口"
    assert len(out) == 1


def test_daily_endpoint_values_are_not_trusted(mod):
    """留档：同花顺 00 接口的"日线"值不可信，日线改由 30min 聚合。

    实测 (2026-09-10 微盘股 883418)：
        00/last.js        → 2179.375
        00/2026.js        → 2167.324   ← 同一接口两次请求值不同
        50/last.js 60min  → 2168.664
        41/last.js 30min  → 2168.664
        当日分时末点       → 2168.664
        官网显示           → 2168.66
    3/5 来源一致且与官网相符 → 分钟线为权威源。

    本测试断言解析器本身仍能正确读 00 格式（保留能力），
    但**业务路径不得使用**（见 test_daily_path_uses_aggregation）。
    """
    # 00 格式仍可解析（字段序正确）
    raw = ["20260910,2186.112,2186.112,2161.042,2167.324,195645730,1254039680.000,,,0"]
    rows = mod._parse_ths_klines(raw)
    assert len(rows) == 1
    assert rows[0]["close"] == pytest.approx(2167.324)
    # 但配置里日线走聚合路径
    assert mod._THS_PERIOD_MAP["883418"][101] == "00", \
        "周期码保留（供历史回填脚本用），但运行时日线走聚合"


def test_parse_minute_timestamp(mod):
    """12 位时间戳 YYYYMMDDHHMM → 'YYYY-MM-DD HH:MM'。"""
    raw = ["202609101500,2181.322,2181.322,2166.574,2168.664,106704200,0,,,0"]
    rows = mod._parse_ths_klines(raw)
    assert rows[0]["bar_time"] == "2026-09-10 15:00"
    assert rows[0]["close"] == pytest.approx(2168.664)


def test_parse_handles_malformed(mod):
    """坏行跳过，不抛异常。"""
    raw = ["", "garbage", "20260910,1,2", "20260910,1,2,0.5,1.5,100,200,,,0"]
    rows = mod._parse_ths_klines(raw)
    assert len(rows) == 1
    assert rows[0]["close"] == pytest.approx(1.5)


# --------------------------------------------------------------------------
# 120min 合成
# --------------------------------------------------------------------------

def test_synth_120min_pairs(mod):
    """10:30+11:30 → 11:30；14:00+15:00 → 15:00。"""
    bars = [
        {"bar_time": "2026-09-10 10:30", "open": 100.0, "high": 105.0,
         "low": 99.0, "close": 104.0, "volume": 10.0, "amount": 1000.0},
        {"bar_time": "2026-09-10 11:30", "open": 104.0, "high": 108.0,
         "low": 103.0, "close": 107.0, "volume": 20.0, "amount": 2000.0},
        {"bar_time": "2026-09-10 14:00", "open": 107.0, "high": 109.0,
         "low": 106.0, "close": 108.0, "volume": 30.0, "amount": 3000.0},
        {"bar_time": "2026-09-10 15:00", "open": 108.0, "high": 110.0,
         "low": 105.0, "close": 106.0, "volume": 40.0, "amount": 4000.0},
    ]
    out = mod._synth_120min_from_60min(bars)
    assert len(out) == 2, "两对应当合成 2 根"
    a, b = out
    # 第一根: 10:30+11:30
    assert a["bar_time"] == "2026-09-10 11:30"
    assert a["open"] == pytest.approx(100.0), "开盘取前一根"
    assert a["high"] == pytest.approx(108.0)
    assert a["low"] == pytest.approx(99.0)
    assert a["close"] == pytest.approx(107.0), "收盘取后一根"
    assert a["volume"] == pytest.approx(30.0)
    # 第二根: 14:00+15:00
    assert b["bar_time"] == "2026-09-10 15:00"
    assert b["close"] == pytest.approx(106.0)


def test_synth_120min_no_partial(mod):
    """不完整的时段（如只有 10:30 没有 11:30）不产出。"""
    bars = [
        {"bar_time": "2026-09-10 10:30", "open": 1.0, "high": 2.0,
         "low": 0.5, "close": 1.5, "volume": 1.0, "amount": 1.0},
    ]
    assert mod._synth_120min_from_60min(bars) == []


# --------------------------------------------------------------------------
# INDICES 配置
# --------------------------------------------------------------------------

def test_indices_microcap_uses_ths(mod):
    """微盘股走同花顺，不再是 tdx_only。"""
    assert "883418" in mod.INDICES
    assert mod.INDICES["883418"].get("ths_only") is True
    assert mod.INDICES["883418"]["name"] == "微盘股"
    assert "880823" not in mod.INDICES, "TDX 880823 已不可用，应移除"


def test_indices_000932_named_consumer(mod):
    """sh000932 实为「中证消费」，原配置误标「中证2000」。"""
    assert mod.INDICES["sh000932"]["name"] == "中证消费"


# --------------------------------------------------------------------------
# 熔断
# --------------------------------------------------------------------------

def test_ths_breaker_short_circuits(mod, monkeypatch):
    """熔断置位后直接返回 []，不再发请求。"""
    monkeypatch.setattr(mod, "_THS_DEAD", True)
    called = {"n": 0}

    def _spy(*a, **k):
        called["n"] += 1
        return [{"bar_time": "x"}]

    monkeypatch.setattr(mod, "fetch_latest_klines_from_ths", _spy)
    assert mod._fetch_ths_with_breaker("883418", 101, 5) == []
    assert called["n"] == 0, "熔断后不应再调用 fetcher"


def test_ths_breaker_trips_on_empty(mod, monkeypatch):
    """空结果触发熔断。"""
    monkeypatch.setattr(mod, "_THS_DEAD", False)
    monkeypatch.setattr(mod, "fetch_latest_klines_from_ths", lambda *a, **k: [])
    assert mod._fetch_ths_with_breaker("883418", 101, 5) == []
    assert mod._THS_DEAD is True
