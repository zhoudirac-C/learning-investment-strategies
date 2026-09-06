"""call_deepseek 限流退避测试。

提案：framework/proposals/2026-09-05-pattern-patch-blind-up-comparison-w36.md
工程问题 3——429/rpm exhausted 时 2s/4s 退避等于无重试（2026-W36 一周 4 次
运行因此缺席），限流错误须排队延时（≥60s）重试。
"""
from types import SimpleNamespace

import pytest

from investment_engine.blindtest import replay


def _ok_resp(content="{}"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=None)


class _FakeCompletions:
    def __init__(self, errors):
        self._errors = list(errors)
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        return _ok_resp()


class _FakeClient:
    def __init__(self, errors):
        self.chat = SimpleNamespace(completions=_FakeCompletions(errors))


def _sleeps(monkeypatch):
    rec = []
    monkeypatch.setattr(replay.time, "sleep", lambda s: rec.append(s))
    monkeypatch.setattr(replay, "_log_llm_call", lambda entry: None)
    return rec


_ERR_429 = Exception("Error code: 429 - {'error': {'message': 'rpm exhausted', "
                     "'type': 'quota_exceeded_error', 'code': '8'}}")


class TestRateLimitBackoff:
    def test_429_waits_over_60s(self, monkeypatch):
        monkeypatch.setenv("SHADOW_LLM_RATE_LIMIT_WAIT", "65")
        rec = _sleeps(monkeypatch)
        client = _FakeClient([_ERR_429, _ERR_429, _ERR_429])
        with pytest.raises(RuntimeError):
            replay.call_deepseek([{"role": "user", "content": "x"}], client=client)
        assert rec == [65.0, 65.0]

    def test_429_eventually_succeeds(self, monkeypatch):
        monkeypatch.setenv("SHADOW_LLM_RATE_LIMIT_WAIT", "65")
        rec = _sleeps(monkeypatch)
        client = _FakeClient([_ERR_429, _ERR_429])  # 第三次成功
        out = replay.call_deepseek([{"role": "user", "content": "x"}], client=client)
        assert out == "{}" and rec == [65.0, 65.0]

    def test_non_rate_limit_keeps_short_backoff(self, monkeypatch):
        monkeypatch.setenv("SHADOW_LLM_RATE_LIMIT_WAIT", "65")
        rec = _sleeps(monkeypatch)
        client = _FakeClient([ValueError("boom"), ValueError("boom")])
        out = replay.call_deepseek([{"role": "user", "content": "x"}], client=client)
        assert out == "{}"
        assert rec == [2, 4]  # 非限流维持原指数退避


class _FakeContentCompletions:
    """按序返回不同 content 的 fake（空 content 重试测试用）。"""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        return _ok_resp(self._contents.pop(0))


class TestEmptyContentRetry:
    """空 content（模型偶发）视为可重试错误，走短退避；持续空则抛错。"""

    def test_blank_content_retried_then_ok(self, monkeypatch):
        rec = _sleeps(monkeypatch)
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=_FakeContentCompletions(["", "  ", "{}"])))
        out = replay.call_deepseek([{"role": "user", "content": "x"}], client=client)
        assert out == "{}"
        assert rec == [2, 4]  # 空 content 非限流，短退避

    def test_persistent_blank_raises(self, monkeypatch):
        rec = _sleeps(monkeypatch)
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=_FakeContentCompletions(["", "", ""])))
        with pytest.raises(RuntimeError, match="空 content"):
            replay.call_deepseek([{"role": "user", "content": "x"}], client=client)
        assert rec == [2, 4]
