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
