import json
import tempfile
from pathlib import Path

import pytest

from qing_investment.agent.tools.kimi_code_acp_client import KimiCodeAcpClient


@pytest.fixture
def fake_acp_factory():
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
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write("\n".join(lines))
            path = f.name
        Path(path).chmod(0o755)
        return path

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
