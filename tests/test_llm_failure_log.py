"""llm_empty 根因留痕：_safe_llm_invoke 失败详情持久化到 logs/llm_failures.jsonl。

背景：2026-10-26 尾盘条件单 job(4e52348bc00f) 报 market_summary LLM 节点失效（llm_empty），
失败证据仅存于内存 tracker + 进程日志，重启即丢失，无法定位当时是超时/限流/5xx。
本测试锁定：失败时落盘 JSONL（provider/stage/prompt_len/elapsed_s/error_type/status_code/error_body），
且 _safe_llm_invoke 在 provider 链耗尽后返回 ""，由调用方诚实降级。
"""

from __future__ import annotations

import json

import pytest

from qing_investment.agent.graph import nodes


class _FakeResp:
    status_code = 429
    text = '{"error":"rate limited"}'


class _FakeAPIError(Exception):
    """模拟 openai.APIStatusError 形态：status_code + response.text"""

    status_code = 429
    response = _FakeResp()

    def __str__(self):
        return "429 rate limited"


@pytest.fixture()
def failure_log(tmp_path, monkeypatch):
    path = tmp_path / "llm_failures.jsonl"
    monkeypatch.setattr(nodes, "_LLM_FAILURE_LOG_PATH", path)
    monkeypatch.setenv("QING_AGENT_FALLBACK_PROVIDERS", "")
    return path


def _read_records(path):
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_persist_llm_failure_writes_jsonl(failure_log):
    nodes._persist_llm_failure(
        provider="hermes_global",
        stage="configured_attempt",
        prompt="x" * 100,
        elapsed_s=1.234,
        error=_FakeAPIError(),
    )
    records = _read_records(failure_log)
    assert len(records) == 1
    rec = records[0]
    assert rec["provider"] == "hermes_global"
    assert rec["stage"] == "configured_attempt"
    assert rec["prompt_len"] == 100
    assert rec["elapsed_s"] == pytest.approx(1.234, abs=0.001)
    assert rec["error_type"] == "_FakeAPIError"
    assert rec["status_code"] == 429
    assert "rate limited" in rec["error_body"]
    assert "ts" in rec


def test_persist_llm_failure_plain_exception_no_status(failure_log):
    nodes._persist_llm_failure(
        provider="hermes_global",
        stage="configured_attempt",
        prompt="hi",
        elapsed_s=0.1,
        error=TimeoutError("connect timeout"),
    )
    rec = _read_records(failure_log)[0]
    assert rec["status_code"] is None
    assert "connect timeout" in rec["error_body"]


def test_safe_llm_invoke_failure_persists_and_returns_empty(failure_log, monkeypatch):
    """失败语义不变：返回 ''，但落盘一条失败记录（含 status_code）。"""

    def _boom(**_kwargs):
        raise _FakeAPIError()

    monkeypatch.setattr(nodes, "get_llm_client", _boom)
    monkeypatch.setenv("KIMI_CODE_ACP_FIRST", "0")
    monkeypatch.delenv("KIMI_CODE_ACP_FIRST", raising=False)

    content = nodes._safe_llm_invoke("测试 prompt", json_mode=True)

    assert content == ""
    records = _read_records(failure_log)
    assert len(records) == 1
    assert records[0]["status_code"] == 429
    assert records[0]["provider"] == "hermes_global"


def test_safe_llm_invoke_failure_body_truncated(failure_log, monkeypatch):
    class _HugeError(Exception):
        def __str__(self):
            return "E" * 2000

    monkeypatch.setattr(
        nodes, "get_llm_client", lambda **_k: (_ for _ in ()).throw(_HugeError())
    )
    monkeypatch.delenv("KIMI_CODE_ACP_FIRST", raising=False)

    nodes._safe_llm_invoke("p")
    rec = _read_records(failure_log)[0]
    assert len(rec["error_body"]) <= 500


def test_safe_llm_invoke_default_fallbacks_log_failures_and_continue(
    failure_log, monkeypatch
):
    from unittest.mock import MagicMock

    from qing_investment.agent.tools import llm_client

    monkeypatch.delenv("QING_AGENT_FALLBACK_PROVIDERS")
    monkeypatch.setattr(nodes.settings, "llm_provider", "sensenova")
    monkeypatch.delenv("KIMI_CODE_ACP_FIRST", raising=False)
    client_calls = []

    def fake_get_llm_client(provider=None):
        client_calls.append(provider)
        if provider == "zhipu":
            raise ValueError("ZHIPU_API_KEY missing")
        fake = MagicMock()
        if provider == "deepseek":
            fake.invoke.return_value = MagicMock(content="")
        else:
            fake.invoke.side_effect = _FakeAPIError()
        return fake

    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)
    llm_client.reset_provider_usage()

    content = nodes._safe_llm_invoke("测试 prompt")

    assert content == ""
    assert client_calls == [None, "zhipu", "deepseek"]
    records = _read_records(failure_log)
    assert [record["provider"] for record in records] == [
        "sensenova", "zhipu", "deepseek"
    ]
    assert [record["stage"] for record in records] == [
        "configured_attempt", "provider_fallback", "provider_fallback"
    ]
    assert [
        (record["provider"], record["status"])
        for record in llm_client.get_provider_usage_records()
    ] == [
        ("sensenova", "attempt"),
        ("sensenova", "failed"),
        ("zhipu", "attempt"),
        ("zhipu", "failed"),
        ("deepseek", "attempt"),
        ("deepseek", "failed"),
    ]
