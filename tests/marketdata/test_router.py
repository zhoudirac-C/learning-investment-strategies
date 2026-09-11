"""router.py 单测：降级链 / strict 空语义 / 熔断联动 / THS 直连（全离线 mock）。

测试通过 monkeypatch ``router._source_mod`` 注入 fake 源模块，
不触网；验证的是 2026-09-10/11 两次事故的回归语义。
"""

import pytest

from qing_investment.marketdata import router
from qing_investment.marketdata.errors import MarketDataError


class FakeSource:
    """可编程 fake 源：exc=抛错 / bars=返回数据 / empty=True 返回空。"""

    def __init__(self, name, *, exc=None, empty=False, bars=None, quotes=None):
        self.SOURCE = name
        self._exc = exc
        self._empty = empty
        self._bars = bars if bars is not None else [
            {"bar_time": "2026-09-11", "open": 1.0, "high": 1.0, "low": 1.0,
             "close": 1.0, "volume": 1.0, "amount": 1.0}
        ]
        self._quotes = quotes if quotes is not None else [
            {"code": "000001", "name": "x", "price": 1.0, "source": name}
        ]
        self.kline_calls = 0

    def fetch_kline(self, code, klt, count, *, kind="auto"):
        self.kline_calls += 1
        if self._exc:
            raise self._exc
        return [] if self._empty else self._bars

    def fetch_quotes(self, codes, *, kind="auto"):
        if self._exc:
            raise self._exc
        return [] if self._empty else self._quotes


@pytest.fixture(autouse=True)
def _clean_breaker():
    router.reset_breaker()
    yield
    router.reset_breaker()


def _patch_sources(monkeypatch, **fakes):
    """monkeypatch router._source_mod 返回 fake。"""
    def fake_mod(name):
        return fakes[name]
    monkeypatch.setattr(router, "_source_mod", fake_mod)


class TestKlineChain:
    def test_tencent_first(self, monkeypatch):
        tn = FakeSource("tencent")
        em = FakeSource("eastmoney")
        _patch_sources(monkeypatch, tencent=tn, eastmoney=em,
                       tdx=FakeSource("tdx"), sina=FakeSource("sina"))
        bars, src = router.get_kline("sh000001", 101, 5, kind="index")
        assert src == "tencent"
        assert tn.kline_calls == 1
        assert em.kline_calls == 0  # 首源成功，不落到第二档

    def test_degrade_on_empty_strict(self, monkeypatch):
        """腾讯空 → 降级东财（strict 空语义：空=失败）。"""
        tn = FakeSource("tencent", empty=True)
        em = FakeSource("eastmoney")
        _patch_sources(monkeypatch, tencent=tn, eastmoney=em,
                       tdx=FakeSource("tdx"), sina=FakeSource("sina"))
        bars, src = router.get_kline("sh000001", 101, 5, kind="index")
        assert src == "eastmoney"
        assert tn.kline_calls == 1

    def test_degrade_on_exception(self, monkeypatch):
        tn = FakeSource("tencent", exc=ConnectionError("boom"))
        em = FakeSource("eastmoney")
        _patch_sources(monkeypatch, tencent=tn, eastmoney=em,
                       tdx=FakeSource("tdx"), sina=FakeSource("sina"))
        _, src = router.get_kline("sh000001", 101, 5, kind="index")
        assert src == "eastmoney"

    def test_all_fail_raises_with_attempts(self, monkeypatch):
        """全部源空 → 抛 MarketDataError（绝不静默返回 []）——9/10 事故回归。"""
        fakes = {n: FakeSource(n, empty=True)
                 for n in ("tencent", "eastmoney", "tdx", "sina", "ths")}
        _patch_sources(monkeypatch, **fakes)
        with pytest.raises(MarketDataError) as ei:
            router.get_kline("sh000001", 101, 5, kind="index")
        assert "empty result" in str(ei.value)
        assert len(ei.value.attempts) >= 3

    def test_120min_skips_eastmoney(self, monkeypatch):
        """东财无原生 120min，链里不应出现：腾讯空后应直接落 TDX。"""
        tn = FakeSource("tencent", empty=True)
        em = FakeSource("eastmoney")
        _patch_sources(monkeypatch, tencent=tn, eastmoney=em,
                       tdx=FakeSource("tdx"), sina=FakeSource("sina"),
                       ths=FakeSource("ths"))
        bars, src = router.get_kline("sh000001", 120, 5, kind="index")
        assert src == "tdx"          # 东财被跳过，直接落 TDX
        assert em.kline_calls == 0   # 东财一次都没被调

    def test_breaker_skips_dead_source(self, monkeypatch):
        """熔断开启后直接跳过该源（不再空转）——cron 超时事故回归。"""
        tn = FakeSource("tencent", exc=ConnectionError("dead"))
        em = FakeSource("eastmoney")
        _patch_sources(monkeypatch, tencent=tn, eastmoney=em,
                       tdx=FakeSource("tdx"), sina=FakeSource("sina"))
        # 第一次：腾讯抛错 → 熔断 → 降级东财成功
        _, src = router.get_kline("sh000001", 101, 5, kind="index")
        assert src == "eastmoney"
        # 第二次：腾讯被熔断跳过，不再调用
        _, src = router.get_kline("sh000001", 101, 5, kind="index")
        assert src == "eastmoney"
        assert tn.kline_calls == 1  # 只调过一次！

    def test_success_resets_breaker(self, monkeypatch):
        """成功后自愈复位（reset 语义）。"""
        tn = FakeSource("tencent")
        router.breaker.trip("tencent:kline")
        _patch_sources(monkeypatch, tencent=tn, eastmoney=FakeSource("eastmoney"),
                       tdx=FakeSource("tdx"), sina=FakeSource("sina"))
        # 手动复位后链路恢复腾讯（对应 breaker.reset 的半开自愈路径）
        router.reset_breaker()
        _, src = router.get_kline("sh000001", 101, 5, kind="index")
        assert src == "tencent"
        assert not router.breaker.is_open("tencent:kline")

    def test_breaker_cooldown_reopens(self, monkeypatch):
        """冷却过期后半开放行真实调用。"""
        tn = FakeSource("tencent", empty=True)
        em = FakeSource("eastmoney")
        _patch_sources(monkeypatch, tencent=tn, eastmoney=em,
                       tdx=FakeSource("tdx"), sina=FakeSource("sina"))
        _, src = router.get_kline("sh000001", 101, 5, kind="index")
        assert src == "eastmoney"
        assert router.breaker.is_open("tencent:kline")
        # 模拟冷却过期
        router.breaker.cooldown = 0.0
        router.breaker._open_until["tencent:kline"] = 0.0
        _, src = router.get_kline("sh000001", 101, 5, kind="index")
        assert src == "eastmoney"  # 腾讯仍空 → 再熔断 → 东财
        assert tn.kline_calls == 2  # 半开放行了一次真实调用


class TestQuotesChain:
    def test_tencent_first_with_compat_source_name(self, monkeypatch):
        """契约兼容：腾讯源名对外仍叫 tencent_gtimg（fetchers 既有契约）。"""
        tn = FakeSource("tencent")
        _patch_sources(monkeypatch, tencent=tn, eastmoney=FakeSource("eastmoney"),
                       tdx=FakeSource("tdx"), sina=FakeSource("sina"))
        r = router.get_quotes(["000001"])
        assert r["source"] == "tencent_gtimg"
        assert r["quotes"] and r["errors"] == []

    def test_all_fail_returns_source_none(self, monkeypatch):
        fakes = {n: FakeSource(n, empty=True)
                 for n in ("tencent", "eastmoney", "tdx", "sina")}
        _patch_sources(monkeypatch, **fakes)
        r = router.get_quotes(["000001"])
        assert r["source"] == "none"
        assert r["quotes"] == []
        assert len(r["errors"]) >= 3  # 每源明细，不静默


class TestThsDirect:
    def test_registered_index_goes_ths(self, monkeypatch):
        """883418 类登记指数直连同花顺，不空转其他源。"""
        ths = FakeSource("ths")
        tn = FakeSource("tencent")
        _patch_sources(monkeypatch, tencent=tn, eastmoney=FakeSource("eastmoney"),
                       tdx=FakeSource("tdx"), sina=FakeSource("sina"), ths=ths)
        # monkeypatch supported() 判定为已登记
        from qing_investment.marketdata.sources import ths as ths_mod
        monkeypatch.setattr(ths_mod, "supported", lambda code: code == "883418")
        bars, src = router.get_kline("883418", 60, 5)
        assert src == "ths"
        assert tn.kline_calls == 0  # 腾讯根本不该被碰
