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


class _FakeFinishCompletions:
    """按序返回 (content, finish_reason) 的 fake（截断重试测试用）。"""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        content, finish_reason = self._outcomes.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                     finish_reason=finish_reason)],
            usage=None)


class TestLengthTruncationRetry:
    """finish_reason=length（max_tokens 截断）视为可重试错误。

    2026-09-07 收盘轨：thinking 推理吃满 32768 上限，JSON 半途被砍，
    截断响应被当作成功返回 → parse 失败当日报废。
    """

    def test_truncated_then_ok(self, monkeypatch):
        rec = _sleeps(monkeypatch)
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=_FakeFinishCompletions([
                ('{"market_stage": "调', "length"),
                ('{"market_stage": "调整"}', "stop"),
            ])))
        out = replay.call_deepseek([{"role": "user", "content": "x"}], client=client)
        assert out == '{"market_stage": "调整"}'
        assert rec == [2]  # 截断非限流，短退避

    def test_persistent_truncation_raises(self, monkeypatch):
        rec = _sleeps(monkeypatch)
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=_FakeFinishCompletions([('{"a', "length")] * 3)))
        with pytest.raises(RuntimeError, match="截断"):
            replay.call_deepseek([{"role": "user", "content": "x"}], client=client)
        assert rec == [2, 4]

    def test_finish_reason_logged_on_ok(self, monkeypatch):
        entries = []
        monkeypatch.setattr(replay, "_log_llm_call", entries.append)
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=_FakeFinishCompletions([("{}", "stop")])))
        replay.call_deepseek([{"role": "user", "content": "x"}], client=client)
        assert entries[0]["finish_reason"] == "stop"


class TestParseFailureRetry:
    """run_with_validation 首版输出非 JSON（多为截断）时带说明重试一次。"""

    _VALID = '{"market_stage": "调整"}'
    _MSGS = [{"role": "user", "content": "x"}]

    @staticmethod
    def _call_seq(outputs):
        it = iter(outputs)
        calls = []

        def _fake(messages, *, model=None, client=None, tag=None):
            calls.append((list(messages), tag))
            return next(it)

        return _fake, calls

    def test_truncated_json_retried_then_pass(self):
        fake, calls = self._call_seq(['{"market_stage": "调', self._VALID])
        raw, result, validation = replay.run_with_validation(
            self._MSGS, call_fn=fake, tag="t")
        assert raw == self._VALID
        assert result["market_stage"] == "调整"
        assert validation["status"] == "passed"
        assert validation["retried"] is True
        assert validation["first_violations"]  # 首版失败如实记录
        assert calls[1][1] == "t_retry"
        # 重试请求带回首版残缺输出供模型参考
        assert calls[1][0][-2]["role"] == "assistant"
        assert calls[1][0][-2]["content"] == '{"market_stage": "调'

    def test_persistent_bad_json_raises(self):
        fake, calls = self._call_seq(['{"a', "still not json"])
        with pytest.raises(ValueError, match="输出非 JSON"):
            replay.run_with_validation(self._MSGS, call_fn=fake, tag="t")
        assert len(calls) == 2  # 只重试一次

    def test_parse_retry_exhausted_then_rule_violation_failed_no_third_call(self):
        # parse 重试已用掉后仍有规则违例：不再发起第三次调用，如实标 failed
        violating = '{"market_stage": "调整", "invalidation": ["成交额跌破20300亿"]}'
        fake, calls = self._call_seq(['{"a', violating])
        raw, result, validation = replay.run_with_validation(
            self._MSGS, call_fn=fake, tag="t")
        assert validation["status"] == "failed"
        assert validation["retried"] is True
        assert len(calls) == 2

    def test_clean_first_pass_untouched(self):
        fake, calls = self._call_seq([self._VALID])
        raw, result, validation = replay.run_with_validation(
            self._MSGS, call_fn=fake, tag="t")
        assert validation == {"status": "passed", "violations": [], "retried": False}
        assert len(calls) == 1
