"""eastmoney_lhb_fetch.py 入口编排测试（monkeypatch 掉网络层）。"""

from __future__ import annotations

import json

import pytest

from investment_engine import eastmoney_lhb
from scripts import eastmoney_lhb_fetch

FAKE_DATA = {"source": "eastmoney", "trade_date": "2026-08-10",
             "fetched_at": "2026-08-10T17:50:02", "stock_count": 2,
             "items": [{"code": "000636", "buy_seats": [], "sell_seats": []},
                       {"code": "600664", "buy_seats": [], "sell_seats": []}],
             "note": ""}


@pytest.fixture
def fake_fetch(monkeypatch):
    monkeypatch.setattr(eastmoney_lhb_fetch.eastmoney_lhb, "fetch_lhb",
                        lambda day, **kw: {**FAKE_DATA, "trade_date": day})


def test_run_success_and_idempotent(tmp_path, capsys, fake_fetch):
    argv = ["--date", "2026-08-10", "--out-root", str(tmp_path)]
    assert eastmoney_lhb_fetch.main(argv) == 0
    out_file = tmp_path / "lhb" / "2026-08-10.json"
    assert out_file.exists()
    assert json.loads(out_file.read_text())["stock_count"] == 2
    assert "上榜=2 只" in capsys.readouterr().out
    # 第二次运行幂等跳过
    assert eastmoney_lhb_fetch.main(argv) == 0
    assert "跳过" in capsys.readouterr().out


def test_fetch_error_exit_code(tmp_path, monkeypatch, capsys):
    def _boom(day, **kw):
        raise eastmoney_lhb.EastmoneyError("重试2次后仍失败")

    monkeypatch.setattr(eastmoney_lhb_fetch.eastmoney_lhb, "fetch_lhb", _boom)
    rc = eastmoney_lhb_fetch.main(["--date", "2026-08-10", "--out-root", str(tmp_path)])
    assert rc == 1
    assert "拉取失败" in capsys.readouterr().err
    assert not (tmp_path / "lhb" / "2026-08-10.json").exists()


def test_force_refetch(tmp_path, fake_fetch):
    argv = ["--date", "2026-08-10", "--out-root", str(tmp_path)]
    assert eastmoney_lhb_fetch.main(argv) == 0
    assert eastmoney_lhb_fetch.main(argv + ["--force"]) == 0
