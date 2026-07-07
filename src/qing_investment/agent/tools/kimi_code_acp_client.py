from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CLI_PATH = "/home/ubuntu/.kimi-code/bin/kimi"
_DEFAULT_CWD = "/home/ubuntu/learning-investment-strategies"
_DEFAULT_TIMEOUT = 300

# ANSI escape sequences may appear in stdout even with TERM=dumb; strip them
# before parsing JSON-RPC messages.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# 将 kimi acp 子进程的 stderr 写入独立日志，便于排查本地模型加载/推理慢的问题
_ACP_STDERR_LOG_DIR = Path.home() / ".kimi-code-im-bot" / "logs"
_ACP_STDERR_LOG_PATH = _ACP_STDERR_LOG_DIR / "kimi-acp-stderr.log"


def _get_acp_stderr_log() -> Any:
    """打开并轮转 ACP stderr 日志（保留最近 5 个备份）。"""
    _ACP_STDERR_LOG_DIR.mkdir(parents=True, exist_ok=True)
    if _ACP_STDERR_LOG_PATH.exists() and _ACP_STDERR_LOG_PATH.stat().st_size > 5 * 1024 * 1024:
        # 超过 5MB 时轮转
        for i in range(4, 0, -1):
            old = _ACP_STDERR_LOG_PATH.with_suffix(f".log.{i}")
            newer = _ACP_STDERR_LOG_PATH.with_suffix(f".log.{i + 1}")
            if old.exists():
                old.rename(newer)
        _ACP_STDERR_LOG_PATH.rename(_ACP_STDERR_LOG_PATH.with_suffix(".log.1"))
    return open(_ACP_STDERR_LOG_PATH, "a", encoding="utf-8", buffering=1)


class KimiCodeAcpError(Exception):
    """ACP client error."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


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
        self.submit_time: float | None = None
        self.first_chunk_time: float | None = None


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
        timeout_env = os.environ.get("KIMI_CODE_ACP_TIMEOUT", "").strip()
        self.timeout = timeout or int(timeout_env if timeout_env else str(_DEFAULT_TIMEOUT))
        self.permission_mode = permission_mode or os.environ.get("KIMI_CODE_ACP_PERMISSION_MODE", "yolo")

        self._child: subprocess.Popen | None = None
        self._next_id = 1
        self._pending: dict[int | str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._shutdown = False
        self._initialized = False
        self._turns: dict[str, _TurnState] = {}

    # ------------------------------------------------------------------
    # Process lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the ACP subprocess and begin reading stdout."""
        if self._child is not None:
            return
        cmd_parts = shlex.split(self.command)
        resolved = shutil.which(os.path.expanduser(cmd_parts[0]))
        if not resolved:
            raise KimiCodeAcpError(f"ACP command not found: {cmd_parts[0]}")
        cmd_parts[0] = resolved
        logger.info("[KimiCodeAcpClient] starting subprocess: %s", " ".join(cmd_parts))
        t0 = time.monotonic()
        self._stderr_log = _get_acp_stderr_log()
        self._child = subprocess.Popen(
            cmd_parts,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_log,
            text=True,
            bufsize=1,
            env={**os.environ, "TERM": "dumb"},
        )
        self._shutdown = False
        self._reader_thread = threading.Thread(target=self._read_lines, daemon=True)
        self._reader_thread.start()
        logger.info("[KimiCodeAcpClient] subprocess started pid=%d startup_ms=%.0f", self._child.pid, (time.monotonic() - t0) * 1000)

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
        # Reset so the next invoke() on this instance re-initializes the
        # new subprocess instead of assuming the old handshake is still valid.
        self._initialized = False
        if hasattr(self, "_stderr_log") and self._stderr_log is not None:
            try:
                self._stderr_log.close()
            except Exception:
                pass
            self._stderr_log = None

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
        # Wait for the response, but abort immediately if the subprocess or
        # reader thread dies so we don't hang for the full timeout.
        deadline = time.monotonic() + self.timeout
        while not event.is_set():
            if self._child is None or self._child.poll() is not None:
                with self._lock:
                    self._pending.pop(req_id, None)
                raise KimiCodeAcpError("ACP subprocess died while waiting for response")
            if self._reader_thread is None or not self._reader_thread.is_alive():
                with self._lock:
                    self._pending.pop(req_id, None)
                raise KimiCodeAcpError("ACP reader thread exited while waiting for response")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            event.wait(min(0.1, remaining))
        if not event.is_set():
            with self._lock:
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
            line = _ANSI_ESCAPE_RE.sub("", line).strip()
            if not line:
                continue
            logger.debug("[KimiCodeAcpClient] recv line: %s", line[:200])
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("[KimiCodeAcpClient] ignoring non-JSON line: %s", line[:200])
                continue
            if "id" in msg and "method" not in msg and ("result" in msg or "error" in msg):
                # JSON-RPC response
                req_id = msg["id"]
                with self._lock:
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
            if not turn.chunks and turn.submit_time:
                turn.first_chunk_time = time.monotonic()
                logger.info("[KimiCodeAcpClient] first chunk latency ms=%.0f",
                            (turn.first_chunk_time - turn.submit_time) * 1000)
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
        invoke_t0 = time.monotonic()
        prompt_len = len(prompt)
        if self._child is None:
            self.start()
        assert self._child is not None

        # 1. Initialize and authenticate if not already done
        if not self._initialized:
            init_t0 = time.monotonic()
            self._send_request("initialize", {
                "protocolVersion": 1,
                "clientInfo": {"name": "qing-agent-acp-client", "version": "0.1.0"},
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
            })
            self._send_request("authenticate", {"methodId": "login"})
            self._initialized = True
            logger.info("[KimiCodeAcpClient] initialize+authenticate done ms=%.0f", (time.monotonic() - init_t0) * 1000)

        # 2. Create a fresh session
        session_t0 = time.monotonic()
        session_result = self._send_request("session/new", {"cwd": self.cwd, "mcpServers": []})
        session_id = session_result.get("sessionId") if isinstance(session_result, dict) else None
        if not session_id:
            raise KimiCodeAcpError(f"ACP session/new returned no sessionId: {session_result}")
        logger.info("[KimiCodeAcpClient] session/new done ms=%.0f", (time.monotonic() - session_t0) * 1000)

        # 3. Set permission mode to avoid interactive approval requests
        if self.permission_mode != "manual":
            cfg_t0 = time.monotonic()
            self._send_request("session/set_config_option", {
                "sessionId": session_id,
                "configId": "mode",
                "value": self.permission_mode,
            })
            logger.info("[KimiCodeAcpClient] set_config_option done ms=%.0f", (time.monotonic() - cfg_t0) * 1000)

        # 4. Register turn state before submitting prompt
        turn = _TurnState(session_id)
        self._turns[session_id] = turn
        turn.submit_time = time.monotonic()

        try:
            # 5. Submit prompt
            prompt_t0 = time.monotonic()
            prompt_result = self._send_request("session/prompt", {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": prompt}],
            })
            prompt_submit_ms = (time.monotonic() - prompt_t0) * 1000
            logger.info("[KimiCodeAcpClient] prompt submitted ms=%.0f prompt_len=%d", prompt_submit_ms, prompt_len)

            # 6. Wait for finish notification, unless the prompt response already
            #    signals turn completion (e.g. {"stopReason": "end_turn"}).
            completed_from_response = (
                isinstance(prompt_result, dict) and prompt_result.get("stopReason") is not None
            )
            if not completed_from_response:
                wait_t0 = time.monotonic()
                if not turn.event.wait(timeout=self.timeout):
                    raise KimiCodeAcpError(f"ACP turn timeout after {self.timeout}s")
                if turn.error:
                    raise KimiCodeAcpError(turn.error)
                logger.info("[KimiCodeAcpClient] turn finished ms=%.0f chunks=%d content_len=%d first_chunk_ms=%.0f total_ms=%.0f",
                            (time.monotonic() - wait_t0) * 1000, len(turn.chunks), len("".join(turn.chunks)),
                            (turn.first_chunk_time - turn.submit_time) * 1000 if turn.first_chunk_time else 0,
                            (time.monotonic() - invoke_t0) * 1000)

            content = "".join(turn.chunks)
            cleaned = self._clean_output(content)
            logger.info("[KimiCodeAcpClient] invoke done total_ms=%.0f prompt_len=%d content_len=%d",
                        (time.monotonic() - invoke_t0) * 1000, prompt_len, len(cleaned))
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
        text = _ANSI_ESCAPE_RE.sub("", text)
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
