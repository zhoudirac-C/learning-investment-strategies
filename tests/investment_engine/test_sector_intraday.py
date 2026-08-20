"""板块分时强度测试（FakeTdx 合成数据，不触网）。

提案：framework/proposals/2026-08-18-data-channel-intraday-sector-strength.md
"""
from pathlib import Path

from investment_engine import sector_intraday as si

PREV = "2026-08-17"
DAY = "2026-08-18"
_HMS = ("10:30", "11:30", "14:00", "15:00")


def _bars(day: str, closes: list[float]) -> list[dict]:
    return [{"datetime": f"{day} {hm}", "close": c} for hm, c in zip(_HMS, closes)]


class FakeTdx:
    """get_kline 按 code 返回预置 60min K 线（时间正序，与 pytdx 一致）。"""

    def __init__(self, series: dict[str, list[dict]]):
        self._series = series

    def get_kline(self, code, category, count=16):
        assert category == "60min"
        return self._series.get(code, [])


def _tdx_defense_pm() -> FakeTdx:
    """防御午后走强、进攻午后走弱 → pm_lead_camp=防御。"""
    return FakeTdx({
        # 银行：昨收 100 → 上午 101 → 收盘 102（午后 +0.99%）
        "880471": _bars(PREV, [100] * 4) + _bars(DAY, [100.5, 101, 101.6, 102]),
        # 半导体：昨收 100 → 上午 100.5 → 收盘 99.5（午后 -1.0%）
        "880491": _bars(PREV, [100] * 4) + _bars(DAY, [100.2, 100.5, 100, 99.5]),
    })


def test_day_am_pm_decomposition():
    data = si.compute_sector_intraday(
        tdx=_tdx_defense_pm(),
        sectors={"880471": {"name": "银行", "camp": "防御"},
                 "880491": {"name": "半导体", "camp": "进攻"}})
    assert data is not None and data["date"] == DAY
    bank = next(r for r in data["sectors"] if r["name"] == "银行")
    assert bank["day_pct"] == 2.0
    assert bank["am_pct"] == 1.0
    assert bank["pm_pct"] == 0.99
    assert bank["marker"] == "真强势"
    semi = next(r for r in data["sectors"] if r["name"] == "半导体")
    assert semi["marker"] == "午后转弱"
    assert data["pm_lead_camp"] == "防御"


def test_offense_lead():
    tdx = FakeTdx({
        "880471": _bars(PREV, [100] * 4) + _bars(DAY, [100, 100.2, 100.1, 100]),
        "880491": _bars(PREV, [100] * 4) + _bars(DAY, [100.5, 101, 102, 103]),
    })
    data = si.compute_sector_intraday(
        tdx=tdx,
        sectors={"880471": {"name": "银行", "camp": "防御"},
                 "880491": {"name": "半导体", "camp": "进攻"}})
    assert data["pm_lead_camp"] == "进攻"


def test_balanced_when_gap_small():
    tdx = FakeTdx({
        "880471": _bars(PREV, [100] * 4) + _bars(DAY, [100, 100.1, 100.15, 100.2]),
        "880491": _bars(PREV, [100] * 4) + _bars(DAY, [100, 100.1, 100.15, 100.2]),
    })
    data = si.compute_sector_intraday(
        tdx=tdx,
        sectors={"880471": {"name": "银行", "camp": "防御"},
                 "880491": {"name": "半导体", "camp": "进攻"}})
    assert data["pm_lead_camp"] == "均衡"


def test_failed_sector_skipped_and_all_failed_returns_none():
    tdx = FakeTdx({})  # 无任何板块数据
    assert si.compute_sector_intraday(
        tdx=tdx, sectors={"880471": {"name": "银行", "camp": "防御"}}) is None


def test_save_and_load_roundtrip(tmp_path: Path):
    data = si.compute_sector_intraday(
        tdx=_tdx_defense_pm(),
        sectors={"880471": {"name": "银行", "camp": "防御"}})
    path = si.save_sector_intraday(data, root=tmp_path)
    assert path.name == "20260818.json"
    loaded = si.load_sector_intraday("2026-08-18", root=tmp_path)
    assert loaded == data
    assert si.load_sector_intraday("2026-08-19", root=tmp_path) is None


def test_default_sectors_are_11_and_balanced_camps():
    camps = [v["camp"] for v in si.SECTORS.values()]
    assert len(si.SECTORS) == 11
    assert camps.count("防御") == 6 and camps.count("进攻") == 5


def test_oversold_rebound_marker():
    """上午深跌+午后回升 → 超跌反弹，不计入真强势。"""
    tdx = FakeTdx({
        "880493": _bars(PREV, [100] * 4) + _bars(DAY, [99, 97.5, 98.5, 99.1]),
    })
    data = si.compute_sector_intraday(
        tdx=tdx, sectors={"880493": {"name": "软件服务", "camp": "进攻"}})
    r = data["sectors"][0]
    assert r["am_pct"] == -2.5 and r["pm_pct"] == 1.64
    assert r["marker"] == "超跌反弹"
    assert data["pm_lead_camp"] == "均衡"  # 无真强势 → 无主导


def test_premarket_stub_and_mixed_dates_guarded():
    """盘前拉取：stub bar（当日 10:30）板块被剔除；混合日期取众数日期。

    2026-08-19 08:52 实测：4 板块带当日 stub（close=昨收 → 0.0% 假行），
    7 板块最新日仍是 8-18；无守卫会落盘 20260819.json 并挡住收盘后真实重拉。
    """
    NEXT = "2026-08-19"
    tdx = FakeTdx({
        # 银行：当日 stub（仅 10:30 一根、close=昨收）→ 剔除
        "880471": _bars(PREV, [100] * 4) + _bars(DAY, [100.2, 100.43, 100.9, 101.21])
                  + [{"datetime": f"{NEXT} 10:30", "close": 101.21}],
        # 半导体：当日 stub → 剔除
        "880491": _bars(PREV, [100] * 4) + _bars(DAY, [99.6, 99.21, 99.8, 100.07])
                  + [{"datetime": f"{NEXT} 10:30", "close": 100.07}],
        # 软件：最新日仍 8-18（完整）→ 保留
        "880493": _bars(PREV, [100] * 4) + _bars(DAY, [98.5, 97.39, 98.3, 98.95]),
    })
    data = si.compute_sector_intraday(
        tdx=tdx,
        sectors={"880471": {"name": "银行", "camp": "防御"},
                 "880491": {"name": "半导体", "camp": "进攻"},
                 "880493": {"name": "软件服务", "camp": "进攻"}})
    assert data["date"] == DAY
    assert [r["name"] for r in data["sectors"]] == ["软件服务"]


def test_20260818_real_shape_defense_leads():
    """8-18 真实形态：防御 2 只真强势（银行/农牧）、进攻 0 只 → 防御。"""
    tdx = FakeTdx({
        "880471": _bars(PREV, [100] * 4) + _bars(DAY, [100.2, 100.43, 100.9, 101.21]),  # 银行 am0.43 pm0.78
        "880360": _bars(PREV, [100] * 4) + _bars(DAY, [101.5, 103.01, 103.4, 103.64]),  # 农牧 am3.01 pm0.61
        "880301": _bars(PREV, [100] * 4) + _bars(DAY, [100.6, 101.21, 101.4, 101.53]),  # 煤炭 pm0.32 平稳
        "880491": _bars(PREV, [100] * 4) + _bars(DAY, [99.6, 99.21, 99.8, 100.07]),    # 半导体 am-0.79 pm0.87
        "880493": _bars(PREV, [100] * 4) + _bars(DAY, [98.5, 97.39, 98.3, 98.95]),      # 软件 am-2.61 pm1.6
    })
    data = si.compute_sector_intraday(
        tdx=tdx,
        sectors={"880471": {"name": "银行", "camp": "防御"},
                 "880360": {"name": "农林牧渔", "camp": "防御"},
                 "880301": {"name": "煤炭", "camp": "防御"},
                 "880491": {"name": "半导体", "camp": "进攻"},
                 "880493": {"name": "软件服务", "camp": "进攻"}})
    markers = {r["name"]: r["marker"] for r in data["sectors"]}
    assert markers["银行"] == "真强势" and markers["农林牧渔"] == "真强势"
    assert markers["煤炭"] == "平稳"
    assert markers["半导体"] == "超跌反弹" and markers["软件服务"] == "超跌反弹"
    assert data["pm_lead_camp"] == "防御"
