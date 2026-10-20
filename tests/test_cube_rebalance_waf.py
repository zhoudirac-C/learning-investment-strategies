"""WAF 567 拦截处置（2026-10-20 用户拍板方案1：只改告警文案，不加重试）。

根因：fetch_current 把 HTTP 567 当单点 RuntimeError → 每组合独立 append →
一次站点级拦截刷 17 条重复告警，且 body[:120] 截出 `<!DOCTYPE html>` 噪声。
修复：567/403/405/429/「访问提示」页 → WafBlocked；主循环 break 本轮；
聚合成一条告警。不重试、不换域名、不重新登录（重试只会延长封锁）。
"""
from __future__ import annotations

import io
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "xueqiu_expert"))

import cube_rebalance_watch as m  # noqa: E402

WAF_HTML = (
    "<!DOCTYPE html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
    "<title>访问提示 - 雪球</title></head><body>请求异常已被安全策略拦截</body></html>"
)


def _http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://www.xueqiu.com/cubes/rebalancing/current.json",
        code, "err", {}, io.BytesIO(body.encode("utf-8")),
    )


class TestWafClassification:
    @pytest.mark.parametrize("code", [567, 403, 405, 429])
    def test_waf_codes_raise_wafblocked(self, monkeypatch, code):
        monkeypatch.setattr(m, "cookie_header", lambda: "xq_a_token=t")
        monkeypatch.setattr(m.time, "sleep", lambda s: None)

        def fake_urlopen(req, timeout=30):
            raise _http_error(code, WAF_HTML)

        monkeypatch.setattr(m.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(m.WafBlocked) as ei:
            m.fetch_current("ZH0000001")
        # 告警文案不得带 HTML
        assert "<!DOCTYPE" not in str(ei.value)
        assert f"HTTP {code}" in str(ei.value)

    def test_challenge_shell_200_is_not_json_silent_bug(self):
        """阿里挑战壳：200 + renderData 但非 JSON → 不能当正常数据。"""
        assert any(s in WAF_HTML for s in m.WAF_BODY_MARKS)

    def test_110017_still_takes_backoff_not_waf(self, monkeypatch):
        """110017（HTTP 400）必须仍走退避，不能被误判成 WAF。"""
        monkeypatch.setattr(m, "cookie_header", lambda: "xq_a_token=t")
        sleeps: list[float] = []
        monkeypatch.setattr(m.time, "sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def fake_urlopen(req, timeout=30):
            calls["n"] += 1
            raise _http_error(400, '{"error_code":110017,"error_description":"操作过于频繁"}')

        monkeypatch.setattr(m.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(m.RateLimited):
            m.fetch_current("ZH0000001")
        assert calls["n"] == 4
        assert sleeps == [60, 120, 180]

    def test_fmt_err_truncates_plain_error(self):
        e = RuntimeError("HTTP 500 " + "x" * 500)
        assert len(m.fmt_err(e)) <= 120


class TestAggregatedAlert:
    def _run(self, monkeypatch, members, fetch):
        monkeypatch.setattr(m, "load_c_members", lambda: members)
        monkeypatch.setattr(m, "load_state", lambda: {})
        monkeypatch.setattr(m, "STATE", Path("/tmp/_cube_watch_state_test.json"))
        monkeypatch.setattr(m, "fetch_current", fetch)
        monkeypatch.setattr(m.time, "sleep", lambda s: None)
        monkeypatch.setattr(sys, "argv", ["cube_rebalance_watch.py"])
        buf = io.StringIO()

        class _Cap(io.StringIO):
            def __init__(self):
                super().__init__()
                self.buf = buf

            def write(self, s):
                return self.buf.write(s)

        monkeypatch.setattr(sys, "stdout", _Cap())
        m.main()
        return buf.getvalue(), m.STATE

    def test_one_waf_wave_emits_single_line_and_stops(self, monkeypatch):
        members = [
            {"uid": str(i), "screen_name": f"u{i}", "rank": i, "group": "g",
             "cube_symbol": f"ZH00000{i}"}
            for i in range(1, 18)
        ]
        calls = {"n": 0}

        def fetch(sym):
            calls["n"] += 1
            raise m.WafBlocked("HTTP 567")

        out, state = self._run(monkeypatch, members, fetch)
        try:
            assert calls["n"] == 1, "WAF 后必须立即中止，不得继续打剩余组合"
            assert out.count("WAF 拦截") == 1
            assert "17 个组合本轮未取到" in out
            assert "<!DOCTYPE" not in out
        finally:
            Path(state).unlink(missing_ok=True)

    def test_normal_errors_still_per_combo(self, monkeypatch):
        """普通单点错误不受影响：仍按组合逐条报（不是通杀）。"""
        members = [
            {"uid": "1", "screen_name": "a", "rank": 1, "group": "g", "cube_symbol": "ZH1"},
            {"uid": "2", "screen_name": "b", "rank": 2, "group": "g", "cube_symbol": "ZH2"},
        ]

        def fetch(sym):
            raise RuntimeError(f"HTTP 500 boom {sym}")

        out, state = self._run(monkeypatch, members, fetch)
        try:
            assert out.count("抓取失败") == 2
            assert "WAF" not in out
        finally:
            Path(state).unlink(missing_ok=True)
