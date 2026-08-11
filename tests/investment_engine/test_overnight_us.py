"""overnight_us.py 单元测试（monkeypatch _get_json，不触网）。"""

from __future__ import annotations

import json

import pytest

from investment_engine import overnight_us as us


def _row(symbol: str, name: str, price_x1000: int, pct_x100: int,
         prev_x1000: int = 0, market: int = 105):
    return {"f12": symbol, "f13": market, "f14": name,
            "f2": price_x1000, "f3": pct_x100, "f18": prev_x1000}


@pytest.fixture
def fake_http(monkeypatch):
    calls = []

    def _fake(params, timeout=10.0, retries=2):
        calls.append(params)
        # 批量响应：COHR 在 106（NYSE），LITE 在 105（NASDAQ），XXXX 无数据
        return {"rc": 0, "data": {"total": 2, "diff": [
            _row("COHR", "Coherent Corp", 1890000, -1205, market=106),
            _row("LITE", "Lumentum Holdings Inc", 813510, -861),
        ]}}

    monkeypatch.setattr(us, "_get_json", _fake)
    return calls


def test_fetch_quotes_single_batch_request(fake_http):
    quotes = us.fetch_quotes(["COHR", "LITE", "XXXX"])
    assert len(fake_http) == 1  # 一次批量请求
    secids = fake_http[0]["secids"].split(",")
    assert len(secids) == 9  # 3 符号 × 3 前缀变体
    assert quotes["COHR"]["secid"] == "106.COHR"
    assert quotes["COHR"]["price"] == 1890.0
    assert quotes["COHR"]["pct_change"] == -12.05
    assert quotes["LITE"]["name"] == "Lumentum Holdings Inc"
    assert "XXXX" not in quotes


def test_fetch_quotes_skips_suspended(monkeypatch):
    monkeypatch.setattr(us, "_get_json", lambda params, timeout=10.0, retries=2:
                        {"rc": 0, "data": {"total": 1, "diff": [
                            {"f12": "HALT", "f13": 105, "f14": "停牌股",
                             "f2": "-", "f3": "-", "f18": "-"}]}})
    assert us.fetch_quotes(["HALT"]) == {}


def test_fetch_overnight_assembles_and_tolerates_missing(tmp_path, fake_http):
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
