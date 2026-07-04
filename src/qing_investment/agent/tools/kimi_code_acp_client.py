from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CLI_PATH = "/home/ubuntu/.kimi-code/bin/kimi"
_DEFAULT_CWD = "/home/ubuntu/learning-investment-strategies"
_DEFAULT_TIMEOUT = 300

# ANSI escape sequences may appear in stdout even with TERM=dumb; strip them
# before parsing JSON-RPC messages.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


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
        """Stub for notifications; Task 2 fills this in."""
        logger.debug("[KimiCodeAcpClient] notification ignored: %s", msg.get("method"))
