import json
from pathlib import Path

import pytest

from qing_investment.agent.tools.kimi_code_acp_client import KimiCodeAcpClient, KimiCodeAcpError


@pytest.fixture
def fake_acp_factory_with_notifications(tmp_path):
    """Factory that creates a shell script mimicking an ACP server.

    The script interleaves JSON-RPC responses to requests with asynchronous
    notifications emitted on a background thread.
    """

    def _make(responses: list[dict], notifications: list[dict]) -> str:
        lines = [
            "#!/usr/bin/env python3",
            "import sys, json, threading, time",
            "responses = " + repr(responses),
            "notifications = " + repr(notifications),
            "idx = 0",
            "def emit_notifications():",
            "    time.sleep(0.05)",
            "    for n in notifications:",
            "        print(json.dumps(n), flush=True)",
            "        time.sleep(0.01)",
            "threading.Thread(target=emit_notifications, daemon=True).start()",
            "for line in sys.stdin:",
            "    line = line.strip()",
            "    if not line: continue",
            "    try: msg = json.loads(line)",
            "    except Exception: continue",
            "    if 'id' in msg and 'method' in msg:",
            "        resp = dict(responses[idx])",
            "        resp['id'] = msg['id']",
            "        print(json.dumps(resp), flush=True)",
            "        idx = (idx + 1) % len(responses)",
            "sys.exit(0)",
        ]
        path = tmp_path / "fake_acp_with_notifications.py"
        path.write_text("\n".join(lines))
        path.chmod(0o755)
        return str(path)

    return _make


@pytest.fixture
def fake_acp_factory(tmp_path):
    """Factory that creates a shell script mimicking an ACP server.

    Usage: fake_acp_factory([response_dict1, response_dict2, ...])
    The script reads stdin JSON-RPC requests and emits the supplied responses
    in order, ignoring notifications.
    """

    def _make(responses: list[dict]) -> str:
        lines = ["#!/usr/bin/env python3", "import sys, json"]
        lines.append("responses = " + repr(responses))
        lines.append("idx = 0")
        lines.append("for line in sys.stdin:")
        lines.append("    line = line.strip()")
        lines.append("    if not line: continue")
        lines.append("    try: msg = json.loads(line)")
        lines.append("    except Exception: continue")
        lines.append("    if 'id' in msg and 'method' in msg:")
        lines.append("        resp = dict(responses[idx])")
        lines.append("        resp['id'] = msg['id']")
        lines.append("        print(json.dumps(resp), flush=True)")
        lines.append("        idx = (idx + 1) % len(responses)")
        lines.append("sys.exit(0)")
        path = tmp_path / "fake_acp.py"
        path.write_text("\n".join(lines))
        path.chmod(0o755)
        return str(path)

    return _make


def test_send_request_receives_response(fake_acp_factory):
    """Fake ACP echoes back the method name as the response result."""
    fake_script = fake_acp_factory([
        {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    ])
    client = KimiCodeAcpClient(command=fake_script, cwd="/tmp")
    client.start()
    try:
        result = client._send_request("initialize", {"protocolVersion": 1})
        assert result == {"ok": True}
    finally:
        client.stop()


def test_get_llm_client_returns_acp_client(monkeypatch):
    """get_llm_client(provider='kimi-code-acp') returns a KimiCodeAcpClient."""
    from qing_investment.agent.tools.llm_client import get_llm_client, _KIMI_CODE_ACP_PROVIDER
    from qing_investment.agent.tools.kimi_code_acp_client import KimiCodeAcpClient

    monkeypatch.setenv("KIMI_CODE_ACP_COMMAND", "echo")
    client = get_llm_client(provider=_KIMI_CODE_ACP_PROVIDER)
    assert isinstance(client, KimiCodeAcpClient)


def test_invoke_aggregates_text_and_returns_response(fake_acp_factory_with_notifications):
    """Fake ACP returns two agent_message_chunk updates then finish."""
    responses = [
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        {"jsonrpc": "2.0", "id": 3, "result": {"sessionId": "s_123"}},
        {"jsonrpc": "2.0", "id": 4, "result": {"stopReason": "done"}},
    ]
    notifications = [
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "s_123",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "hello "}},
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "s_123",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "world"}},
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": "s_123", "update": {"sessionUpdate": "finish"}},
        },
    ]
    script = fake_acp_factory_with_notifications(responses, notifications)
    client = KimiCodeAcpClient(command=script, cwd="/tmp")
    try:
        resp = client.invoke("say hello")
        assert resp.content == "hello world"
    finally:
        client.stop()


def test_invoke_raises_on_subprocess_timeout(fake_acp_factory_with_notifications):
    """If ACP never sends finish, invoke should raise KimiCodeAcpError."""
    responses = [
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        {"jsonrpc": "2.0", "id": 3, "result": {"sessionId": "s_timeout"}},
        {"jsonrpc": "2.0", "id": 4, "result": {"stopReason": "done"}},
    ]
    notifications = []  # never finish
    script = fake_acp_factory_with_notifications(responses, notifications)
    client = KimiCodeAcpClient(command=script, cwd="/tmp", timeout=1)
    with pytest.raises(KimiCodeAcpError):
        client.invoke("prompt")


def test_start_raises_when_command_missing():
    client = KimiCodeAcpClient(command="/nonexistent/kimi-acp", cwd="/tmp")
    with pytest.raises(KimiCodeAcpError):
        client.start()


def test_send_request_raises_when_subprocess_crashes(tmp_path):
    """If the ACP subprocess exits after receiving a request but before
    responding, _send_request should raise KimiCodeAcpError promptly."""
    script_path = tmp_path / "fake_acp_crash.py"
    script_path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "for line in sys.stdin:\n"
        "    if line.strip():\n"
        "        sys.exit(0)\n"
    )
    script_path.chmod(0o755)
    client = KimiCodeAcpClient(command=str(script_path), cwd="/tmp", timeout=5)
    client.start()
    try:
        with pytest.raises(KimiCodeAcpError):
            client._send_request("initialize", {"protocolVersion": 1})
    finally:
        client.stop()
