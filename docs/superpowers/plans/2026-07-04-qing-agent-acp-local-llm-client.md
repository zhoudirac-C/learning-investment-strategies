# Qing-Agent ACP Local LLM Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `kimi -p` argv-based local CLI invocation with an ACP-over-stdio client that spawns an independent `kimi acp` process, sends prompts via JSON-RPC, and aggregates responses, while reusing the existing Kimi Code login credentials and without polluting Feishu user sessions.

**Architecture:** Add a `KimiCodeAcpClient` Python class that wraps a persistent `kimi acp` subprocess, speaks JSON-RPC 2.0 over stdin/stdout, creates a fresh ACP session per LLM invoke, submits the prompt, waits for `finish`, and returns the aggregated text. Register a new `kimi-code-acp` provider in `llm_client.py` and wire it into `_safe_llm_invoke` in `nodes.py` behind an environment-variable flag.

**Tech Stack:** Python 3.11, `subprocess`, JSON-RPC 2.0, `pytest`, LangChain-compatible `.invoke(prompt).content` interface.

## Global Constraints

- Use Python 3.11 type hints and `from __future__ import annotations`.
- All new files go under `src/qing_investment/agent/tools/`.
- All new tests go under `tests/`.
- Keep the existing `_safe_llm_invoke(prompt: str, min_length: int = 0) -> str` signature unchanged.
- The ACP client must expose a LangChain-like `.invoke(prompt).content` interface so `nodes.py` needs no signature changes.
- Reuse existing Kimi Code credentials at `~/.kimi-code/credentials/kimi-code.json`; do not implement a separate login flow.
- Each `_safe_llm_invoke` call must use a fresh ACP session to avoid cross-node context pollution.
- The ACP subprocess must be isolated from the Feishu bridge process; do not connect to a shared `kimi server`.
- Clean up ACP sessions after each invoke to avoid leaking sessions.
- Default timeout is 300s, overridable via `KIMI_CODE_ACP_TIMEOUT`.
- Default permission mode is `yolo`, overridable via `KIMI_CODE_ACP_PERMISSION_MODE`.
- The implementation must include tests using a fake ACP process so CI does not need a real `kimi` binary.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/qing_investment/agent/tools/kimi_code_acp_client.py` | New ACP client: subprocess management, JSON-RPC, session lifecycle, text aggregation, LangChain-compatible response. |
| `src/qing_investment/agent/tools/llm_client.py` | Register `kimi-code-acp` provider in `get_llm_client`. |
| `src/qing_investment/agent/graph/nodes.py` | Wire `kimi-code-acp` into `_safe_llm_invoke` behind `KIMI_CODE_ACP_FIRST`. |
| `tests/test_kimi_code_acp_client.py` | Unit tests for JSON-RPC transport, session lifecycle, text aggregation, and timeout handling with a fake ACP process. |
| `tests/test_kimi_code_acp_integration.py` | Regression tests for `_safe_llm_invoke` fallback and `min_length` behavior using a mocked ACP client. |

---

### Task 1: Create `KimiCodeAcpClient` JSON-RPC transport

**Files:**
- Create: `src/qing_investment/agent/tools/kimi_code_acp_client.py`
- Test: `tests/test_kimi_code_acp_client.py`

**Interfaces:**
- Consumes: nothing
- Produces: `class KimiCodeAcpClient` with methods `start()`, `stop()`, `_send_request(method, params)`, `_send_notification(method, params)`, and internal line reader.

- [ ] **Step 1: Write the failing test for JSON-RPC request/response roundtrip**

```python
# tests/test_kimi_code_acp_client.py
import json
import pytest
from qing_investment.agent.tools.kimi_code_acp_client import KimiCodeAcpClient


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kimi_code_acp_client.py::test_send_request_receives_response -v`

Expected: FAIL with `KimiCodeAcpClient not defined` or similar.

- [ ] **Step 3: Implement minimal JSON-RPC transport**

```python
# src/qing_investment/agent/tools/kimi_code_acp_client.py
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CLI_PATH = "/home/ubuntu/.kimi-code/bin/kimi"
_DEFAULT_CWD = "/home/ubuntu/learning-investment-strategies"
_DEFAULT_TIMEOUT = 300


class KimiCodeAcpError(Exception):
    """ACP client error."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class KimiCodeAcpClient:
    """Kimi Code ACP client over stdio (JSON-RPC 2.0).

    Spawns an independent `kimi acp` subprocess, sends prompts via JSON-RPC,
    and aggregates responses. One client instance manages one subprocess;
    each `.invoke()` call creates a fresh ACP session.
    """

    def __init__(
        self,
        command: str | None = None,
        cwd: str | None = None,
        timeout: int | None = None,
        permission_mode: str | None = None,
    ):
        self.command = command or os.environ.get("KIMI_CODE_ACP_COMMAND") or f"{_DEFAULT_CLI_PATH} acp"
        self.cwd = cwd or os.environ.get("KIMI_CODE_ACP_CWD") or _DEFAULT_CWD
        self.timeout = timeout or int(os.environ.get("KIMI_CODE_ACP_TIMEOUT", str(_DEFAULT_TIMEOUT)))
        self.permission_mode = permission_mode or os.environ.get("KIMI_CODE_ACP_PERMISSION_MODE", "yolo")

        self._child: subprocess.Popen | None = None
        self._next_id = 1
        self._pending: dict[int | str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._shutdown = False

    # ------------------------------------------------------------------
    # Process lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the ACP subprocess and begin reading stdout."""
        if self._child is not None:
            return
        cmd_parts = self.command.split()
        resolved = shutil.which(cmd_parts[0])
        if not resolved:
            raise KimiCodeAcpError(f"ACP command not found: {cmd_parts[0]}")
        cmd_parts[0] = resolved
        logger.info("[KimiCodeAcpClient] starting subprocess: %s", " ".join(cmd_parts))
        self._child = subprocess.Popen(
            cmd_parts,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env={**os.environ, "TERM": "dumb"},
        )
        self._shutdown = False
        self._reader_thread = threading.Thread(target=self._read_lines, daemon=True)
        self._reader_thread.start()

    def stop(self) -> None:
        """Stop the ACP subprocess."""
        self._shutdown = True
        child = self._child
        self._child = None
        if child is not None:
            try:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
            except Exception as e:
                logger.warning("[KimiCodeAcpClient] error stopping subprocess: %s", e)
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=5)

    # ------------------------------------------------------------------
    # JSON-RPC primitives
    # ------------------------------------------------------------------
    def _send_request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC request and wait for a response."""
        if self._child is None or self._child.stdin is None:
            raise KimiCodeAcpError("ACP subprocess is not running")
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
        event = threading.Event()
        result_container: dict[str, Any] = {}
        self._pending[req_id] = {"event": event, "result": result_container}
        req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        line = json.dumps(req, ensure_ascii=False)
        logger.debug("[KimiCodeAcpClient] send request: %s", line)
        self._child.stdin.write(f"{line}\n")
        self._child.stdin.flush()
        if not event.wait(timeout=self.timeout):
            self._pending.pop(req_id, None)
            raise KimiCodeAcpError(f"ACP request timeout: {method}")
        if "error" in result_container:
            raise KimiCodeAcpError(f"ACP request failed: {result_container['error']}")
        return result_container.get("result")

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (fire and forget)."""
        if self._child is None or self._child.stdin is None:
            raise KimiCodeAcpError("ACP subprocess is not running")
        req = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        line = json.dumps(req, ensure_ascii=False)
        logger.debug("[KimiCodeAcpClient] send notification: %s", line)
        self._child.stdin.write(f"{line}\n")
        self._child.stdin.flush()

    def _read_lines(self) -> None:
        """Background thread: read JSON-RPC lines from stdout."""
        if self._child is None or self._child.stdout is None:
            return
        for line in self._child.stdout:
            line = line.strip()
            if not line:
                continue
            logger.debug("[KimiCodeAcpClient] recv line: %s", line[:200])
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("[KimiCodeAcpClient] ignoring non-JSON line: %s", line[:200])
                continue
            if "id" in msg and "method" not in msg:
                # Response
                req_id = msg["id"]
                pending = self._pending.pop(req_id, None)
                if pending is not None:
                    if "error" in msg:
                        pending["result"]["error"] = msg["error"]
                    else:
                        pending["result"]["result"] = msg.get("result")
                    pending["event"].set()
            elif "method" in msg and "id" not in msg:
                # Notification - handled later in Task 2
                self._handle_notification(msg)
        logger.info("[KimiCodeAcpClient] stdout reader exited")

    def _handle_notification(self, msg: dict[str, Any]) -> None:
        """Stub for notifications; Task 2 fills this in."""
        logger.debug("[KimiCodeAcpClient] notification ignored: %s", msg.get("method"))
```

- [ ] **Step 4: Add fake ACP fixture for tests**

```python
# tests/test_kimi_code_acp_client.py
import json
import tempfile
from pathlib import Path

import pytest


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
```

- [ ] **Step 5: Run tests and verify they pass**

Run: `pytest tests/test_kimi_code_acp_client.py::test_send_request_receives_response -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_kimi_code_acp_client.py src/qing_investment/agent/tools/kimi_code_acp_client.py
git commit -m "feat(agent): add KimiCodeAcpClient JSON-RPC transport"
```

---

### Task 2: Add ACP session management and prompt invocation

**Files:**
- Modify: `src/qing_investment/agent/tools/kimi_code_acp_client.py`
- Test: `tests/test_kimi_code_acp_client.py`

**Interfaces:**
- Consumes: `_send_request`, `_send_notification`, `_handle_notification` from Task 1.
- Produces: `class KimiCodeAcpResponse` with `.content: str`; `KimiCodeAcpClient.invoke(prompt: str) -> KimiCodeAcpResponse`.

- [ ] **Step 1: Write the failing test for `.invoke()` end-to-end**

```python
# tests/test_kimi_code_acp_client.py

def test_invoke_aggregates_text_and_returns_response(fake_acp_factory):
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
    resp = client.invoke("say hello")
    assert resp.content == "hello world"
```

Update the fake ACP fixture to interleave notifications after request responses:

```python
@pytest.fixture
def fake_acp_factory_with_notifications():
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
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write("\n".join(lines))
            path = f.name
        Path(path).chmod(0o755)
        return path

    return _make
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kimi_code_acp_client.py::test_invoke_aggregates_text_and_returns_response -v`

Expected: FAIL with `AttributeError: 'KimiCodeAcpClient' object has no attribute 'invoke'`.

- [ ] **Step 3: Implement session management, event aggregation, and `.invoke()`**

Add to `kimi_code_acp_client.py`:

```python
import re
import uuid


class KimiCodeAcpResponse:
    """LangChain-compatible response wrapper."""

    def __init__(self, content: str):
        self.content = content

    def __repr__(self) -> str:
        return f"KimiCodeAcpResponse(content_len={len(self.content)})"


class _TurnState:
    """Per-session turn state used while waiting for finish."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.event = threading.Event()
        self.chunks: list[str] = []
        self.error: str | None = None
        self.finished = False


class KimiCodeAcpClient:
    # ... existing code from Task 1 ...

    def __init__(self, ...):
        # ... existing init ...
        self._turns: dict[str, _TurnState] = {}

    def _handle_notification(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        if method != "session/update":
            logger.debug("[KimiCodeAcpClient] ignoring notification: %s", method)
            return
        params = msg.get("params") or {}
        session_id = params.get("sessionId")
        update = params.get("update") or {}
        update_type = update.get("sessionUpdate")
        if not session_id or not update_type:
            return
        turn = self._turns.get(session_id)
        if turn is None:
            logger.debug("[KimiCodeAcpClient] no turn for session %s", session_id)
            return
        if update_type == "agent_message_chunk":
            text = (update.get("content") or {}).get("text") or ""
            turn.chunks.append(text)
        elif update_type == "finish":
            turn.finished = True
            turn.event.set()
        elif update_type == "error":
            turn.error = (update.get("message") or "ACP turn error").strip() or "ACP turn error"
            turn.event.set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def invoke(self, prompt: str) -> KimiCodeAcpResponse:
        """Create a fresh ACP session, send one prompt, return aggregated text."""
        if self._child is None:
            self.start()
        assert self._child is not None

        # 1. Initialize and authenticate if not already done
        if not getattr(self, "_initialized", False):
            self._send_request("initialize", {
                "protocolVersion": 1,
                "clientInfo": {"name": "qing-agent-acp-client", "version": "0.1.0"},
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
            })
            self._send_request("authenticate", {"methodId": "login"})
            self._initialized = True

        # 2. Create a fresh session
        session_result = self._send_request("session/new", {"cwd": self.cwd, "mcpServers": []})
        session_id = session_result.get("sessionId") if isinstance(session_result, dict) else None
        if not session_id:
            raise KimiCodeAcpError(f"ACP session/new returned no sessionId: {session_result}")

        # 3. Set permission mode to avoid interactive approval requests
        if self.permission_mode != "manual":
            self._send_request("session/set_config_option", {
                "sessionId": session_id,
                "configId": "mode",
                "value": self.permission_mode,
            })

        # 4. Register turn state before submitting prompt
        turn = _TurnState(session_id)
        self._turns[session_id] = turn

        try:
            # 5. Submit prompt
            self._send_request("session/prompt", {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": prompt}],
            })

            # 6. Wait for finish
            if not turn.event.wait(timeout=self.timeout):
                raise KimiCodeAcpError(f"ACP turn timeout after {self.timeout}s")
            if turn.error:
                raise KimiCodeAcpError(turn.error)

            content = "".join(turn.chunks)
            cleaned = self._clean_output(content)
            return KimiCodeAcpResponse(content=cleaned)
        finally:
            # 7. Best-effort cleanup
            self._turns.pop(session_id, None)
            try:
                self._send_notification("session/close", {"sessionId": session_id})
            except Exception as e:
                logger.debug("[KimiCodeAcpClient] session/close failed: %s", e)

    def _clean_output(self, text: str) -> str:
        """Conservative output cleaning (same strategy as CLI client).

        1. Strip ANSI escape codes.
        2. Try to extract the first valid JSON object/array.
        3. Otherwise return stripped text.
        """
        text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
        text = text.strip()
        # Try whole text as JSON
        for candidate in (text, text.strip("`").lstrip("json").strip()):
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass
        # Try longest valid JSON substring
        for start_char, end_char in (("{", "}"), ("[", "]")):
            start = text.find(start_char)
            if start == -1:
                continue
            for end in range(len(text), start, -1):
                if text[end - 1] != end_char:
                    continue
                candidate = text[start:end]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and not parsed:
                        continue
                    if isinstance(parsed, list) and not parsed:
                        continue
                    return candidate
                except json.JSONDecodeError:
                    continue
        return text
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_kimi_code_acp_client.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_kimi_code_acp_client.py src/qing_investment/agent/tools/kimi_code_acp_client.py
git commit -m "feat(agent): add ACP session lifecycle and invoke()"
```

---

### Task 3: Register `kimi-code-acp` provider in `llm_client.py`

**Files:**
- Modify: `src/qing_investment/agent/tools/llm_client.py`

**Interfaces:**
- Consumes: `KimiCodeAcpClient` and `KimiCodeAcpResponse` from Task 2.
- Produces: `get_llm_client(provider="kimi-code-acp")` returns a `KimiCodeAcpClient` instance.

- [ ] **Step 1: Write the failing test for provider registration**

```python
# tests/test_kimi_code_acp_client.py (append)

def test_get_llm_client_returns_acp_client(monkeypatch):
    """get_llm_client(provider='kimi-code-acp') returns a KimiCodeAcpClient."""
    from qing_investment.agent.tools.llm_client import get_llm_client, _KIMI_CODE_ACP_PROVIDER
    from qing_investment.agent.tools.kimi_code_acp_client import KimiCodeAcpClient

    monkeypatch.setenv("KIMI_CODE_ACP_COMMAND", "echo")
    client = get_llm_client(provider=_KIMI_CODE_ACP_PROVIDER)
    assert isinstance(client, KimiCodeAcpClient)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kimi_code_acp_client.py::test_get_llm_client_returns_acp_client -v`

Expected: FAIL with `ImportError` or `ValueError: Unknown LLM provider`.

- [ ] **Step 3: Implement provider registration**

Modify `src/qing_investment/agent/tools/llm_client.py`:

```python
# Near _KIMI_CODE_CLI_PROVIDER
_KIMI_CODE_ACP_PROVIDER = "kimi-code-acp"

# In get_llm_client, after the kimi-code-cli block:
if target == _KIMI_CODE_ACP_PROVIDER:
    from .kimi_code_acp_client import KimiCodeAcpClient

    logger.info("[get_llm_client] using local Kimi Code ACP")
    return KimiCodeAcpClient()

if target not in LLM_PROVIDERS:
    raise ValueError(
        f"Unknown LLM provider: {target}. "
        f"Supported: {', '.join(LLM_PROVIDERS.keys())}, {_KIMI_CODE_CLI_PROVIDER}, {_KIMI_CODE_ACP_PROVIDER}"
    )
```

Also update the earlier error message if it references only `_KIMI_CODE_CLI_PROVIDER`.

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_kimi_code_acp_client.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/qing_investment/agent/tools/llm_client.py tests/test_kimi_code_acp_client.py
git commit -m "feat(agent): register kimi-code-acp provider in llm_client"
```

---

### Task 4: Wire ACP into `_safe_llm_invoke`

**Files:**
- Modify: `src/qing_investment/agent/graph/nodes.py`

**Interfaces:**
- Consumes: `get_llm_client(provider="kimi-code-acp")`, `KimiCodeAcpClient.invoke`.
- Produces: `_safe_llm_invoke` supports `KIMI_CODE_ACP_FIRST` env var and falls back to configured provider.

- [ ] **Step 1: Write the failing integration test for `_safe_llm_invoke` with ACP**

```python
# tests/test_kimi_code_acp_integration.py
import json
from unittest.mock import MagicMock

import pytest

from qing_investment.agent.graph import nodes


def _fake_response(content: str):
    class _R:
        def __init__(self, c):
            self.content = c
    return _R(content)


def test_safe_llm_invoke_acp_first_with_fallback(monkeypatch):
    """When KIMI_CODE_ACP_FIRST=1 and ACP returns too-short output, fall back to provider."""
    monkeypatch.setenv("KIMI_CODE_ACP_FIRST", "1")

    acp = MagicMock()
    acp.invoke.return_value = _fake_response("short")
    remote = MagicMock()
    remote.invoke.return_value = _fake_response("fallback remote content")

    def fake_get_llm_client(provider=None):
        if provider == "kimi-code-acp":
            return acp
        return remote

    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)

    result = nodes._safe_llm_invoke("prompt", min_length=50)
    assert result == "fallback remote content"
    acp.invoke.assert_called_once_with("prompt")
    remote.invoke.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kimi_code_acp_integration.py::test_safe_llm_invoke_acp_first_with_fallback -v`

Expected: FAIL because `_safe_llm_invoke` does not check `KIMI_CODE_ACP_FIRST`.

- [ ] **Step 3: Modify `_safe_llm_invoke` to support ACP**

In `src/qing_investment/agent/graph/nodes.py`, update the docstring and logic of `_safe_llm_invoke`:

```python
def _safe_llm_invoke(prompt: str, min_length: int = 0) -> str:
    """安全调用 LLM，默认走配置 provider。

    通过环境变量控制本地调用优先级：
    - KIMI_CODE_ACP_FIRST=1 / true：优先本地 Kimi Code ACP（stdio JSON-RPC）
    - KIMI_CODE_CLI_FIRST=1 / true：优先本地 Kimi Code CLI（kimi -p，受 argv 限制）
    - 否则：直接走 settings.llm_provider

    Args:
        prompt: 发送给 LLM 的提示。
        min_length: 本地调用返回内容的最小可接受长度（字符数）。
            若返回内容长度低于此值，视为失败并 fallback 到配置 provider。
    """
    import os

    acp_first = os.environ.get("KIMI_CODE_ACP_FIRST", "0").lower() not in ("0", "false", "no")
    cli_first = os.environ.get("KIMI_CODE_CLI_FIRST", "0").lower() not in ("0", "false", "no")

    local_providers = []
    if acp_first:
        local_providers.append("kimi-code-acp")
    if cli_first:
        local_providers.append("kimi-code-cli")

    for local_provider in local_providers:
        logger.info("[_safe_llm_invoke] 优先尝试 %s", local_provider)
        record_provider_usage(local_provider, "attempt", "local-first enabled")
        try:
            local_llm = get_llm_client(provider=local_provider)
            content = local_llm.invoke(prompt).content
            record_provider_usage(local_provider, "success", f"content_len={len(content)}")
            logger.info(
                "[_safe_llm_invoke] %s 成功, content_len=%d, tracker=%s",
                local_provider,
                len(content),
                format_provider_usage_summary(get_provider_usage_records()),
            )
            if min_length > 0 and len(content) < min_length:
                raise RuntimeError(
                    f"{local_provider} returned too short output ({len(content)} chars, min={min_length})"
                )
            return content
        except Exception as e:
            record_provider_usage(local_provider, "failed", str(e)[:120])
            logger.warning(
                "[_safe_llm_invoke] %s 失败: %s, 将 fallback 到 %s",
                local_provider, e, settings.llm_provider,
            )

    # fallback / 直接走配置 provider
    logger.info("[_safe_llm_invoke] 调用配置 provider: %s", settings.llm_provider)
    record_provider_usage(settings.llm_provider, "fallback" if local_providers else "attempt")
    try:
        llm = get_llm_client()
        content = llm.invoke(prompt).content
        record_provider_usage(settings.llm_provider, "success", f"content_len={len(content)}")
        logger.info(
            "[_safe_llm_invoke] provider %s 成功, content_len=%d, tracker=%s",
            settings.llm_provider,
            len(content),
            format_provider_usage_summary(get_provider_usage_records()),
        )
        return content
    except Exception as e:
        record_provider_usage(settings.llm_provider, "failed", str(e)[:120])
        logger.warning(
            "[_safe_llm_invoke] provider %s 失败: %s, tracker=%s",
            settings.llm_provider,
            e,
            format_provider_usage_summary(get_provider_usage_records()),
        )
        return ""
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_kimi_code_acp_integration.py tests/test_kimi_code_cli_short_output.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/qing_investment/agent/graph/nodes.py tests/test_kimi_code_acp_integration.py
git commit -m "feat(agent): wire kimi-code-acp into _safe_llm_invoke with fallback"
```

---

### Task 5: Add timeout and process-crash tests

**Files:**
- Modify: `tests/test_kimi_code_acp_client.py`

**Interfaces:**
- Consumes: `KimiCodeAcpClient` from Task 2.
- Produces: confidence that the client handles bad subprocess behavior.

- [ ] **Step 1: Write tests for timeout and process exit**

```python
# tests/test_kimi_code_acp_client.py

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
    with pytest.raises(Exception):
        client.invoke("prompt")


def test_start_raises_when_command_missing():
    client = KimiCodeAcpClient(command="/nonexistent/kimi-acp", cwd="/tmp")
    with pytest.raises(Exception):
        client.start()
```

- [ ] **Step 2: Run tests and verify behavior**

Run: `pytest tests/test_kimi_code_acp_client.py::test_invoke_raises_on_subprocess_timeout tests/test_kimi_code_acp_client.py::test_start_raises_when_command_missing -v`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_kimi_code_acp_client.py
git commit -m "test(agent): add ACP timeout and missing-binary tests"
```

---

### Task 6: Add documentation and environment variable reference

**Files:**
- Modify: `src/qing_investment/agent/tools/kimi_code_acp_client.py` (docstring already added in Task 2)
- Modify: `src/qing_investment/agent/tools/llm_client.py` (docstring already updated in Task 3)
- Create: `docs/superpowers/plans/2026-07-04-qing-agent-acp-local-llm-client-env.md` (optional env reference)

**Interfaces:**
- Consumes: completed implementation.
- Produces: operational docs for users.

- [ ] **Step 1: Create environment variable reference doc**

```markdown
# Kimi Code ACP Client Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KIMI_CODE_ACP_FIRST` | `0` | Set to `1` to make `_safe_llm_invoke` try ACP before the configured provider. |
| `KIMI_CODE_ACP_COMMAND` | `~/.kimi-code/bin/kimi acp` | Command used to launch the ACP subprocess. |
| `KIMI_CODE_ACP_CWD` | `/home/ubuntu/learning-investment-strategies` | Working directory for the ACP subprocess and new sessions. |
| `KIMI_CODE_ACP_TIMEOUT` | `300` | Maximum seconds to wait for a single ACP turn. |
| `KIMI_CODE_ACP_PERMISSION_MODE` | `yolo` | ACP permission mode; use `manual` or `auto` if you need interactive approvals. |

## Migration from `kimi -p`

The old `kimi-code-cli` provider passed the prompt as a command-line argument,
which hit OS `ARG_MAX` limits on large prompts. The new `kimi-code-acp` provider
spawns an independent `kimi acp` subprocess and sends prompts via JSON-RPC over
stdio, avoiding argv limits entirely.

To enable:

```bash
export KIMI_CODE_ACP_FIRST=1
```

To keep using the old CLI:

```bash
export KIMI_CODE_CLI_FIRST=1
```

Both fall back to the configured API provider on failure.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-07-04-qing-agent-acp-local-llm-client-env.md
git commit -m "docs(agent): add ACP client environment variable reference"
```

---

### Task 7: Final integration verification

**Files:**
- All of the above.

- [ ] **Step 1: Run the full test suite for affected modules**

Run:

```bash
pytest tests/test_kimi_code_acp_client.py tests/test_kimi_code_acp_integration.py tests/test_kimi_code_cli_short_output.py tests/test_market_summary.py tests/test_market_analyst_split.py -v
```

Expected: all PASS.

- [ ] **Step 2: Run lint/type-check if configured**

Check project conventions:

```bash
# If ruff is installed:
ruff check src/qing_investment/agent/tools/kimi_code_acp_client.py src/qing_investment/agent/tools/llm_client.py src/qing_investment/agent/graph/nodes.py tests/test_kimi_code_acp_client.py tests/test_kimi_code_acp_integration.py

# If mypy is installed:
mypy src/qing_investment/agent/tools/kimi_code_acp_client.py
```

Expected: no new errors.

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "chore(agent): final ACP client integration and verification"
```

---

## Self-Review

**1. Spec coverage:**

| Requirement | Task |
|-------------|------|
| Spawn independent `kimi acp` subprocess | Task 1, 2 |
| Send prompt via JSON-RPC (not argv) | Task 1, 2 |
| Fresh ACP session per LLM invoke | Task 2 |
| Reuse existing Kimi Code login credentials | Task 2 (reads same `~/.kimi-code/credentials/kimi-code.json`) |
| Do not pollute Feishu sessions | Task 2 (independent subprocess + per-invoke session) |
| LangChain-compatible `.invoke().content` | Task 2 |
| Fallback to configured provider | Task 4 |
| `min_length` support | Task 4 |
| Tests without real `kimi` binary | Task 1, 2, 5 |

**2. Placeholder scan:**

- No "TBD", "TODO", or "implement later".
- No "add appropriate error handling" without code.
- No "similar to Task N".
- Every task includes exact file paths, code, and commands.

**3. Type consistency:**

- `KimiCodeAcpClient.invoke(prompt: str) -> KimiCodeAcpResponse`
- `KimiCodeAcpResponse.content: str`
- `_safe_llm_invoke` signature unchanged.
- `get_llm_client(provider="kimi-code-acp")` returns `KimiCodeAcpClient`.

No inconsistencies found.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-04-qing-agent-acp-local-llm-client.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
