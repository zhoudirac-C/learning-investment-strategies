"""breaker.py 单测：能力粒度熔断 + 半开自愈。"""

from qing_investment.marketdata.breaker import Breaker


class TestBreaker:
    def test_initially_closed(self):
        b = Breaker("test", cooldown=60)
        assert not b.is_open("kline")

    def test_trip_and_open(self):
        b = Breaker("test", cooldown=60)
        b.trip("kline")
        assert b.is_open("kline")
        assert not b.is_open("quotes")  # 能力粒度：其他能力不受影响

    def test_half_open_after_cooldown(self):
        b = Breaker("test", cooldown=0.05)
        b.trip("kline")
        import time
        time.sleep(0.06)
        assert not b.is_open("kline")  # 冷却过期 → 半开放行

    def test_reset_single(self):
        b = Breaker("test", cooldown=60)
        b.trip("kline")
        b.trip("quotes")
        b.reset("kline")
        assert not b.is_open("kline")
        assert b.is_open("quotes")

    def test_reset_all(self):
        b = Breaker("test", cooldown=60)
        b.trip("kline")
        b.trip("quotes")
        b.reset()
        assert not b.is_open("kline")
        assert not b.is_open("quotes")
