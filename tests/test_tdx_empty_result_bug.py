"""TDX 空结果静默吞掉 bug 的回归测试（2026-09-10）。

背景：2026-09-10 全量实测发现 TDX 公网 7709 节点**按接口粒度封禁**——
`get_security_bars` / `get_index_bars` 在所有 host 上返回空，
但 `get_security_count` / `get_security_list` 正常。

由于 `execute()` 在「全部 host 返回空」时**返回最后的空结果而不抛异常**，
上层 `get_kline()` 把它变成 `[]`，于是：
  - `tdx_market_selftest.py` 报 OK（[] 不抛异常）
  - `update_index_klines_intraday.py` 逐台空转 22 台 host，直至 cron 900s 超时

本测试锁定修复后的契约：**K线类能力全部空 → 必须抛 TdxDataError**，
而不是静默返回 []。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from qing_investment.tdx_market.client import TdxClient, _is_empty  # noqa: E402
from qing_investment.tdx_market.exceptions import (  # noqa: E402
    TdxConnectionError,
    TdxDataError,
)
from qing_investment.tdx_market.hosts import HostCapability  # noqa: E402


def _fake_hosts(n: int = 4):
    """构造 n 台可用 host（直接 monkeypatch 候选列表，不碰网络）。"""
    from qing_investment.tdx_market import client as client_mod
    from qing_investment.tdx_market.hosts import (
        HostClassMain,
        HostInfo,
        mainCapabilities,
    )

    hosts = [
        HostInfo(f"t{i}", f"测试host{i}", f"10.0.0.{i}", 7709,
                 HostClassMain, mainCapabilities, "test", 100)
        for i in range(1, n + 1)
    ]
    client_mod._all_hosts = lambda: hosts  # type: ignore[assignment]
    # HostsForCapability 也走 hosts 模块，需要一起 patch
    import qing_investment.tdx_market.hosts as hosts_mod
    orig = hosts_mod.HostsForCapability
    hosts_mod.HostsForCapability = lambda cap: [h for h in hosts if h.Enabled and (h.Capabilities & cap)]
    return hosts, orig, hosts_mod


def test_is_empty_helper():
    assert _is_empty(None) is True
    assert _is_empty([]) is True
    assert _is_empty({}) is True
    assert _is_empty("") is True
    assert _is_empty([1]) is False
    assert _is_empty({"a": 1}) is False
    assert _is_empty(0) is False  # 标量不算空（成交笔数=0 是合法值）


def test_kline_all_empty_raises_data_error(monkeypatch):
    """核心回归：所有 host 都返回空 K线 + strict=True → 必须抛 TdxDataError。

    修复前行为：返回 None / []，静默成功。
    """
    _fake_hosts(4)
    c = TdxClient(max_attempts=4)

    def _always_empty(host, cap, op, args, kwargs):
        return None  # 服务端「连上但返回空」的典型表现

    monkeypatch.setattr(TdxClient, "_run_on_host", staticmethod(_always_empty))

    with pytest.raises(TdxDataError):
        c.execute(
            HostCapability.CapMainKline, lambda api: None,
            retry_empty=True, strict=True,
        )


def test_market_get_kline_raises_on_all_empty(monkeypatch):
    """端到端：TdxMarket.get_kline 在 TDX 全空时必须抛异常，不能返回 []。

    这正是 2026-09-10 的故障路径 —— get_index_kline 返回 []，
    导致 tdx_market_selftest 报 OK、update_index_klines_intraday 空转超时。
    """
    from qing_investment.tdx_market.market import TdxMarket

    _fake_hosts(4)
    mkt = TdxMarket(client=TdxClient(max_attempts=4))
    monkeypatch.setattr(
        TdxClient, "_run_on_host", staticmethod(lambda *a, **k: None)
    )
    with pytest.raises(TdxDataError):
        mkt.get_index_kline("999999", count=5)


def test_market_get_kline_ok_when_data(monkeypatch):
    """有真实数据时必须正常返回 K线（不能被 strict 误伤）。"""
    from qing_investment.tdx_market.market import TdxMarket

    _fake_hosts(4)
    mkt = TdxMarket(client=TdxClient(max_attempts=4))
    bars = [
        {"open": 3900, "close": 3910, "high": 3920, "low": 3890,
         "vol": 100, "amount": 1e6, "year": 2026, "month": 9,
         "day": 10, "hour": 15, "minute": 0},
    ]
    monkeypatch.setattr(
        TdxClient, "_run_on_host", staticmethod(lambda *a, **k: bars)
    )
    out = mkt.get_index_kline("999999", count=5)
    assert len(out) == 1
    assert out[0]["close"] == 3910


def test_metadata_all_empty_still_returns(monkeypatch):
    """对照组：非严格能力（元数据）全部空时，保持原「返回空」语义，
    避免把证券列表等场景一起变成硬错误。"""
    _fake_hosts(3)
    c = TdxClient(max_attempts=3)
    monkeypatch.setattr(
        TdxClient, "_run_on_host", staticmethod(lambda *a, **k: None)
    )
    res = c.execute(HostCapability.CapMainList, lambda api: None, retry_empty=True)
    assert res is None


def test_hard_error_still_raises_connection_error(monkeypatch):
    """控制组：硬异常路径不受本次修改影响。"""
    _fake_hosts(3)
    c = TdxClient(max_attempts=3)

    def _boom(*a, **k):
        raise TdxConnectionError("boom")

    monkeypatch.setattr(TdxClient, "_run_on_host", staticmethod(_boom))
    with pytest.raises(TdxConnectionError):
        c.execute(HostCapability.CapMainKline, lambda api: None, retry_empty=True)


def test_partial_success_returns_data(monkeypatch):
    """只要有任意一台返回数据，就正常返回，不抛异常。"""
    _fake_hosts(4)
    c = TdxClient(max_attempts=4)
    calls = {"n": 0}

    def _second_works(host, cap, op, args, kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            return [{"open": 1, "close": 2}]
        return None

    monkeypatch.setattr(TdxClient, "_run_on_host", staticmethod(_second_works))
    res = c.execute(HostCapability.CapMainKline, lambda api: None, retry_empty=True)
    assert res == [{"open": 1, "close": 2}]
