"""kpl_daily_fetch.py 入口编排测试（monkeypatch 掉网络层）。"""

from __future__ import annotations

import json

import pytest

from investment_engine.kpl.client import KplAuthError
from scripts import kpl_daily_fetch


@pytest.fixture
def fake_layers(monkeypatch):
    monkeypatch.setattr(kpl_daily_fetch.KplClient, "from_env",
                        classmethod(lambda cls: object()))
    monkeypatch.setattr(kpl_daily_fetch.emotion, "fetch_snapshot",
                        lambda client: {"date": "2026-08-10",
                                        "fetched_at": "2026-08-10T15:45:02",
                                        "daban": {"tZhangTing": 76, "tFengBan": 85.4},
                                        "lianban": [["600721", "百花医药", 9.96, 1,
                                                     "5连板", "医药", "医药;2"]],
                                        "erban": [], "fengkou": [], "bankuai": [],
                                        "fengxiang": {}})
    monkeypatch.setattr(kpl_daily_fetch.news, "fetch_day_news",
                        lambda client, day: ([{"ID": 1, "Title": "t", "CreateTime": 1,
                                               "MsgType": 5, "Stock": [], "imgList": [],
                                               "Content": "<p>x</p>"}], []))
    monkeypatch.setattr(kpl_daily_fetch.lhb, "fetch_lhb",
                        lambda client: {"date": "2026-08-10",
                                        "fetched_at": "2026-08-10T17:45:02",
                                        "disclosure_day": "2026-08-10",
                                        "prev_disclosure_day": "2026-08-07",
                                        "tlist": [], "list": [{"StockID": "600664"}],
                                        "entry_count": 1, "note": ""})


def test_run_success_and_idempotent(tmp_path, capsys, fake_layers):
    argv = ["--date", "2026-08-10", "--out-root", str(tmp_path)]
    assert kpl_daily_fetch.main(argv) == 0
    emotion_file = tmp_path / "emotion" / "2026-08-10.json"
    news_index = tmp_path / "news" / "2026-08-10" / "index.json"
    assert emotion_file.exists() and news_index.exists()
    assert json.loads(emotion_file.read_text())["daban"]["tZhangTing"] == 76
    # 第二次运行幂等跳过
    assert kpl_daily_fetch.main(argv) == 0
    assert "跳过" in capsys.readouterr().out


def test_auth_error_exit_code(tmp_path, monkeypatch, capsys, fake_layers):
    def _boom(client):
        raise KplAuthError("登录已过期")

    monkeypatch.setattr(kpl_daily_fetch.emotion, "fetch_snapshot", _boom)
    rc = kpl_daily_fetch.main(["--date", "2026-08-10", "--out-root", str(tmp_path)])
    assert rc == 3
    assert "登录已过期" in capsys.readouterr().err


def test_lhb_written_and_skip_flag(tmp_path, capsys, fake_layers):
    argv = ["--date", "2026-08-10", "--out-root", str(tmp_path)]
    assert kpl_daily_fetch.main(argv) == 0
    lhb_file = tmp_path / "lhb" / "2026-08-10.json"
    assert lhb_file.exists()
    assert json.loads(lhb_file.read_text())["list"][0]["StockID"] == "600664"
    argv2 = ["--date", "2026-08-11", "--out-root", str(tmp_path), "--skip-lhb"]
    assert kpl_daily_fetch.main(argv2) == 0
    assert not (tmp_path / "lhb" / "2026-08-11.json").exists()
