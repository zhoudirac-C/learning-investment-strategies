"""全球宏观快照测试（fake fetcher 合成数据，不触网）。

提案：framework/proposals/2026-08-20-data-channel-global-macro.md
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_engine import global_macro as gm

ET = -4 * 3600   # 美东夏令时 gmtoffset
KST = 9 * 3600   # 韩国


def _chart(bars: list[tuple[str, float]], gmtoffset: int = ET) -> dict:
    """[(session_date, close)] → Yahoo chart result[0]（bar ts=当地 09:30）。"""
    ts, closes = [], []
    for d, c in bars:
        y, m, dd = map(int, d.split("-"))
        open_utc = (datetime(y, m, dd, 9, 30, tzinfo=timezone.utc)
                    - timedelta(seconds=gmtoffset))
        ts.append(int(open_utc.timestamp()))
        closes.append(c)
    return {"meta": {"gmtoffset": gmtoffset, "symbol": "X"},
            "timestamp": ts, "indicators": {"quote": [{"close": closes}]}}


def _fetcher(series: dict[str, dict]):
    return lambda sym: series[sym]


# 08-19 复盘（22:00 北京 = 14:00 UTC）：美股 08-19 session 盘中未收盘 → 排除
def test_unclosed_us_session_excluded():
    series = {"^IXIC": _chart([("2026-08-17", 100.0), ("2026-08-18", 95.0),
                               ("2026-08-19", 90.0)])}
    data = gm.compute_global_macro("2026-08-19", fetcher=_fetcher(series),
                                   symbols={"^IXIC": {"name": "纳指", "group": "美股三指数",
                                                      "close": (16, 0)}})
    row = data["美股三指数"]["纳指"]
    assert row["session"] == "2026-08-18"
    assert row["close"] == 95.0 and row["pct"] == -5.0


# 同日亚太 session 已收盘（14:30 北京）→ 计入当日
def test_asia_same_day_session_included():
    series = {"^KS11": _chart([("2026-08-18", 100.0), ("2026-08-19", 94.2)],
                              gmtoffset=KST)}
    data = gm.compute_global_macro("2026-08-19", fetcher=_fetcher(series),
                                   symbols={"^KS11": {"name": "KOSPI", "group": "亚太股指",
                                                      "close": (15, 30)}})
    row = data["亚太股指"]["KOSPI"]
    assert row["session"] == "2026-08-19" and row["pct"] == -5.8


# 美债收益率：水平 + 基点变动（day=08-20 → 美股 08-19 session 已完整）
def test_treasury_yield_bp_change():
    series = {"^TYX": _chart([("2026-08-18", 5.24), ("2026-08-19", 5.196)])}
    data = gm.compute_global_macro("2026-08-20", fetcher=_fetcher(series),
                                   symbols={"^TYX": {"name": "30Y", "group": "美债收益率",
                                                     "close": (16, 0), "kind": "yield"}})
    row = data["美债收益率"]["30Y"]
    assert row["session"] == "2026-08-19"
    assert row["yield"] == 5.196 and row["chg_bp"] == -4.4


# 历史日重算防泄漏：拉取时刻晚于 day 时，asof 仍封顶 day 22:00 北京
def test_backfill_asof_capped_at_review_close():
    series = {"^KS11": _chart([("2026-08-18", 98.0), ("2026-08-19", 100.0),
                               ("2026-08-20", 106.46)], gmtoffset=KST)}
    later = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc).timestamp()
    data = gm.compute_global_macro("2026-08-19", fetcher=_fetcher(series),
                                   now_ts=later,
                                   symbols={"^KS11": {"name": "KOSPI", "group": "亚太股指",
                                                      "close": (15, 30)}})
    row = data["亚太股指"]["KOSPI"]
    assert row["session"] == "2026-08-19" and row["pct"] == 2.04


def test_all_failed_returns_none():
    def _boom(sym):
        raise RuntimeError("proxy dead")
    assert gm.compute_global_macro("2026-08-19", fetcher=_boom) is None


def test_partial_failure_recorded_in_errors():
    def _fetch(sym):
        if sym == "^SOX":
            raise RuntimeError("rate limited")
        return _chart([("2026-08-18", 100.0), ("2026-08-19", 101.0)])
    data = gm.compute_global_macro("2026-08-20", fetcher=_fetch, throttle=0)
    assert data is not None
    assert "费城半导体" not in data
    assert any(e.startswith("^SOX") for e in data["errors"])
    assert data["美股三指数"]["纳指"]["pct"] == 1.0


def test_bar_with_none_close_skipped():
    series = {"^IXIC": _chart([("2026-08-18", 100.0), ("2026-08-19", 103.0)])}
    series["^IXIC"]["indicators"]["quote"][0]["close"].insert(1, None)
    series["^IXIC"]["timestamp"].insert(1, series["^IXIC"]["timestamp"][0] + 86400)
    data = gm.compute_global_macro("2026-08-20", fetcher=_fetcher(series),
                                   symbols={"^IXIC": {"name": "纳指", "group": "美股三指数",
                                                      "close": (16, 0)}})
    assert data["美股三指数"]["纳指"]["pct"] == 3.0


def test_save_and_load_roundtrip(tmp_path: Path):
    series = {"^IXIC": _chart([("2026-08-18", 100.0), ("2026-08-19", 103.0)])}
    data = gm.compute_global_macro("2026-08-20", fetcher=_fetcher(series),
                                   symbols={"^IXIC": {"name": "纳指", "group": "美股三指数",
                                                      "close": (16, 0)}})
    path = gm.save_global_macro(data, root=tmp_path)
    assert path.name == "20260820.json"
    assert gm.load_global_macro("2026-08-20", root=tmp_path) == data
    assert gm.load_global_macro("2026-08-19", root=tmp_path) is None


def test_default_symbols_cover_proposal_fields():
    groups = {v["group"] for v in gm.SYMBOLS.values()}
    assert set(gm.GROUPS) == groups
    names = {v["name"] for v in gm.SYMBOLS.values()}
    for want in ("道指", "纳指", "标普", "费城半导体", "美光", "闪迪", "希捷",
                 "西数", "铠侠", "KOSPI", "日经225", "恒生", "13W", "10Y", "30Y",
                 "美元指数", "黄金", "铜"):  # 13W/黄金/铜：2026-09-05 增补（08-26/08-27 闭环）
        assert want in names
