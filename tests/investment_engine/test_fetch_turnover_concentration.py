#!/usr/bin/env python3
"""脚本侧测试：fetch_turnover_concentration.py 的分页重试与落盘护栏。

覆盖 2026-10-14/10-15 断档事故（东财 clist 单页 RemoteDisconnected 导致整体失败）：
- 单页瞬时失败 → 退避重试后成功
- 单页持续失败 → 抛最后一次异常（不吞错）
- 覆盖度不足 → 拒绝落盘
- 同日已存在 → 幂等跳过
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "fetch_turnover_concentration", ROOT / "scripts" / "fetch_turnover_concentration.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load_module()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """重试退避不真睡，测试才快。"""
    import time
    monkeypatch.setattr(time, "sleep", lambda *_: None)


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _page(codes_amounts, total=None):
    diff = [{"f12": c, "f6": a} for c, a in codes_amounts]
    return {"data": {"total": total if total is not None else len(diff), "diff": diff}}


class TestRetry:
    def test_transient_failure_then_success(self, mod, monkeypatch):
        """前 2 次抛连接错误，第 3 次成功 → 重试生效，结果正常返回。"""
        import requests
        calls = {"n": 0}

        def fake_get(url, **kw):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise requests.exceptions.ConnectionError(
                    "RemoteDisconnected: Remote end closed connection without response")
            return _FakeResp(_page([("600127", 1.0e9)]))

        monkeypatch.setattr(requests, "get", fake_get)
        rows = mod.fetch_all()
        assert calls["n"] == 3  # 2 失败 + 1 成功
        assert len(rows) == 1
        assert rows[0]["f12"] == "600127"

    def test_persistent_failure_raises_last(self, mod, monkeypatch):
        """全部重试都失败 → 抛异常，不静默返回空列表。"""
        import requests
        calls = {"n": 0}

        def always_fail(url, **kw):
            calls["n"] += 1
            raise requests.exceptions.ConnectionError("always fail")

        monkeypatch.setattr(requests, "get", always_fail)
        with pytest.raises(requests.exceptions.ConnectionError):
            mod.fetch_all()
        assert calls["n"] == mod.MAX_RETRIES

    def test_http_error_also_retried(self, mod, monkeypatch):
        """HTTP 状态码异常（raise_for_status）同样走重试。"""
        import requests
        calls = {"n": 0}

        class _BadResp(_FakeResp):
            def raise_for_status(self):
                raise requests.exceptions.HTTPError("503 Server Error")

        def fake_get(url, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return _BadResp(_page([]))
            return _FakeResp(_page([("600127", 1.0e9)]))

        monkeypatch.setattr(requests, "get", fake_get)
        rows = mod.fetch_all()
        assert calls["n"] == 2
        assert len(rows) == 1


class TestMainGuards:
    def _stub_fetch(self, mod, monkeypatch, rows):
        monkeypatch.setattr(mod, "fetch_all", lambda: rows)

    def test_rejects_low_coverage(self, mod, monkeypatch, tmp_path, capsys):
        """覆盖不足 4000 只 → 拒绝落盘 + 非零退出。"""
        monkeypatch.setattr(mod, "OUT_DIR", tmp_path)
        self._stub_fetch(mod, monkeypatch,
                         [{"f12": f"{i:06d}", "f6": 1.0e8} for i in range(100)])
        monkeypatch.setattr(sys, "argv", ["x", "--date", "2026-10-14"])
        assert mod.main() == 1
        assert not (tmp_path / "2026-10-14.json").exists()
        assert "覆盖异常" in capsys.readouterr().err

    def test_writes_when_coverage_ok(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "OUT_DIR", tmp_path)
        self._stub_fetch(mod, monkeypatch,
                         [{"f12": f"{i:06d}", "f6": 1.0e8} for i in range(5000)])
        monkeypatch.setattr(sys, "argv", ["x", "--date", "2026-10-14"])
        assert mod.main() == 0
        data = json.loads((tmp_path / "2026-10-14.json").read_text(encoding="utf-8"))
        assert data["date"] == "2026-10-14"
        assert data["n_stocks"] == 5000

    def test_idempotent_same_day(self, mod, monkeypatch, tmp_path):
        """同日文件已存在 → 跳过且不覆盖（幂等）。"""
        existing = tmp_path / "2026-10-14.json"
        existing.write_text('{"date": "2026-10-14", "concentration_pct": 1.0}', encoding="utf-8")
        monkeypatch.setattr(mod, "OUT_DIR", tmp_path)
        self._stub_fetch(mod, monkeypatch,
                         [{"f12": f"{i:06d}", "f6": 1.0e8} for i in range(5000)])
        monkeypatch.setattr(sys, "argv", ["x", "--date", "2026-10-14"])
        assert mod.main() == 0
        assert json.loads(existing.read_text(encoding="utf-8"))["concentration_pct"] == 1.0

    def test_force_overwrites(self, mod, monkeypatch, tmp_path):
        existing = tmp_path / "2026-10-14.json"
        existing.write_text('{"date": "2026-10-14", "concentration_pct": 1.0}', encoding="utf-8")
        monkeypatch.setattr(mod, "OUT_DIR", tmp_path)
        self._stub_fetch(mod, monkeypatch,
                         [{"f12": f"{i:06d}", "f6": 1.0e8} for i in range(5000)])
        monkeypatch.setattr(sys, "argv", ["x", "--date", "2026-10-14", "--force"])
        assert mod.main() == 0
        assert json.loads(existing.read_text(encoding="utf-8"))["concentration_pct"] != 1.0
