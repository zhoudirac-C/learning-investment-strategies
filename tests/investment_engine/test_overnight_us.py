"""overnight_us.py 单元测试（monkeypatch _get_tencent_raw，不触网）。"""

from __future__ import annotations

import json

import pytest

from investment_engine import overnight_us as us


def _line(symbol: str, name: str, price: str, pct: str, prev: str = "0") -> str:
    """构造腾讯 v_usXXX="..." 行（字段用 ~ 分隔，涨跌幅在 [32]）。"""
    fields = ["200", name, f"{symbol}.OQ", price, prev, "0"]  # 0-5
    fields += ["0"] * 26  # 6-31
    fields += [pct]  # 32 涨跌幅
    fields += ["0", "0", "USD"]  # 33-35
    return f'v_us{symbol}="{"~".join(fields)}";'


@pytest.fixture
def fake_http(monkeypatch):
    calls = []

    def _fake(symbols, timeout=10.0, retries=2):
        calls.append(symbols)
        return "\n".join([
            _line("COHR", "Coherent Corp", "189.00", "-12.05", "215.00"),
            _line("LITE", "Lumentum Holdings Inc", "81.35", "-8.61", "89.00"),
            # XXXX 无返回行（腾讯对无效代码不返回行）
        ])

    monkeypatch.setattr(us, "_get_tencent_raw", _fake)
    return calls


def test_fetch_quotes_single_batch_request(fake_http):
    quotes = us.fetch_quotes(["COHR", "LITE", "XXXX"])
    assert len(fake_http) == 1  # 一次批量请求
    assert fake_http[0] == ["COHR", "LITE", "XXXX"]
    assert quotes["COHR"]["secid"] == "usCOHR"
    assert quotes["COHR"]["price"] == 189.0
    assert quotes["COHR"]["pct_change"] == -12.05
    assert quotes["LITE"]["name"] == "Lumentum Holdings Inc"
    assert "XXXX" not in quotes


def test_fetch_quotes_skips_suspended(monkeypatch):
    monkeypatch.setattr(
        us, "_get_tencent_raw",
        lambda symbols, timeout=10.0, retries=2: _line("HALT", "停牌股", "-", "-", "-"))
    assert us.fetch_quotes(["HALT"]) == {}


def test_fetch_overnight_assembles_and_tolerates_missing(tmp_path, fake_http, monkeypatch):
    monkeypatch.setattr(us, "fetch_movers", lambda **kw: None)  # 不触网
    cfg = tmp_path / "us_map.yaml"
    cfg.write_text("""themes:
  - id: optical_module
    name: 光模块/CPO
    symbols:
      - {symbol: COHR, name: Coherent, earnings_note: "美东8/12盘后财报"}
      - {symbol: LITE, name: Lumentum, earnings_note: ""}
      - {symbol: XXXX, name: 不存在的, earnings_note: ""}
""", encoding="utf-8")
    data = us.fetch_overnight(cfg)
    theme = data["themes"][0]
    ok = [s for s in theme["stocks"] if "error" not in s]
    err = [s for s in theme["stocks"] if "error" in s]
    assert len(ok) == 2 and len(err) == 1
    assert ok[0]["earnings_note"] == "美东8/12盘后财报"
    assert "1 只无数据" in data["note"]

    path = us.save_overnight(data, tmp_path, "2026-08-11")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["themes"][0]["stocks"][0]["pct_change"] == -12.05


# ---------------------------------------------------------------------------
# 隔夜美股异动扫描（2026-08-21 调研落地：Yahoo 预定义榜单经代理）
# 提案：framework/proposals/2026-08-21-pattern-patch-blind-up-comparison.md 配套缺口 2
# 回归场景：2026-08-19 MRNA +177%（表外大异动，盲判不可见）/ 08-20 MRNA -24.5%。
# ---------------------------------------------------------------------------


def _q(symbol, pct, mcap, name="X", price=10.0):
    return {"symbol": symbol, "shortName": name, "regularMarketChangePercent": pct,
            "regularMarketPrice": price, "marketCap": mcap}


class TestMovers:
    def test_filter_thresholds_and_sort(self):
        quotes = [
            _q("MRNA", 177.0, 5.254e10, "Moderna", 174.38),
            _q("SMALL", 50.0, 5e8),          # 市值不足 20 亿美元
            _q("WEAK", 6.0, 5e9),            # 幅度不足 8%
            _q("AAP", -27.2, 2.47e9, "Advance Auto", 40.9),
            _q("BIG", 12.0, 4.0e10, "BigCo", 100.0),
        ]
        gainers = us._filter_movers(quotes, "gainers")
        losers = us._filter_movers(quotes, "losers")
        assert [m["symbol"] for m in gainers] == ["MRNA", "BIG"]  # 涨幅降序
        assert [m["symbol"] for m in losers] == ["AAP"]
        assert gainers[0]["mcap_亿美元"] == 525.4
        assert losers[0]["pct_change"] == -27.2

    def test_missing_fields_skipped(self):
        quotes = [_q("NOPE", None, 5e9), _q("NOMCAP", 30.0, None)]
        assert us._filter_movers(quotes, "gainers") == []

    def test_fetch_movers_with_injected_fetch(self):
        def fake(side, **kw):
            return {"day_gainers": [_q("MRNA", 177.0, 5.254e10, "Moderna")],
                    "day_losers": [_q("AAP", -27.2, 2.47e9, "Advance")]}[side]

        m = us.fetch_movers(fetch_fn=fake)
        assert m["gainers"][0]["symbol"] == "MRNA"
        assert m["losers"][0]["symbol"] == "AAP"
        assert "8%" in m["note"] and "20亿" in m["note"]

    def test_fetch_overnight_movers_failure_degrades(self, tmp_path, fake_http, monkeypatch):
        """异动扫描失败（代理故障等）不阻断主题映射：movers=None + 错误如实记录。"""
        def _boom(**kw):
            raise us.OvernightUsError("proxy down")

        monkeypatch.setattr(us, "fetch_movers", _boom)
        cfg = tmp_path / "us_map.yaml"
        cfg.write_text("""themes:
  - id: optical_module
    name: 光模块/CPO
    symbols:
      - {symbol: COHR, name: Coherent, earnings_note: ""}
""", encoding="utf-8")
        data = us.fetch_overnight(cfg)
        assert data["movers"] is None
        assert "proxy down" in data["movers_error"]
        assert data["themes"][0]["stocks"][0]["symbol"] == "COHR"  # 主题不受影响

    def test_fetch_overnight_movers_present(self, tmp_path, fake_http, monkeypatch):
        monkeypatch.setattr(us, "fetch_movers",
                            lambda **kw: {"gainers": [{"symbol": "MRNA"}], "losers": [],
                                          "note": "n"})
        cfg = tmp_path / "us_map.yaml"
        cfg.write_text("""themes:
  - id: optical_module
    name: 光模块/CPO
    symbols:
      - {symbol: COHR, name: Coherent, earnings_note: ""}
""", encoding="utf-8")
        data = us.fetch_overnight(cfg)
        assert data["movers"]["gainers"][0]["symbol"] == "MRNA"
