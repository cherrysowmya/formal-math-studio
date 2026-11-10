"""Small, persistent JSON-RPC stdio client for local MCP tools."""
from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import threading
import time


class ToolError(RuntimeError):
    pass


class Cancelled(ToolError):
    pass


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)


class MCPClient:
    def __init__(self, command: list[str], *, cwd=None, env=None, timeout=240):
        self.command = command
        self.cwd = cwd
        self.env = env
        self.timeout = timeout
        self.process = None
        self.selector = None
        self.buffer = bytearray()
        self.sequence = 0
        self.tools: set[str] = set()
        self.lock = threading.RLock()

    def start(self, cancel: threading.Event) -> None:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return
            if not self.command:
                raise ToolError("No local MCP command configured")
            self.close()
            try:
                self.process = subprocess.Popen(self.command, cwd=self.cwd, env=self.env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    start_new_session=True, bufsize=0)
            except OSError as exc:
                raise ToolError(f"Cannot start local tool {self.command[0]}: {exc}") from exc
            self.selector = selectors.DefaultSelector()
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
            try:
                self._request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "formal-math-studio", "version": "0.1.0"}}, cancel)
                self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})
                result = self._request("tools/list", {}, cancel)
                self.tools = {item["name"] for item in result.get("tools", [])}
            except Exception:
                self.close()
                raise

    def _write(self, value: dict) -> None:
        if self.process is None or self.process.stdin is None:
            raise ToolError("Local MCP process is not running")
        try:
            self.process.stdin.write((json.dumps(value) + "\n").encode())
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ToolError("Local MCP process exited") from exc

    def _request(self, method: str, params: dict, cancel: threading.Event):
        self.sequence += 1
        request_id = self.sequence
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            if cancel.is_set():
                self.close()
                raise Cancelled("Run cancelled")
            if time.monotonic() >= deadline:
                self.close()
                raise ToolError(f"Local MCP request timed out: {method}")
            if b"\n" not in self.buffer:
                if not self.selector.select(min(.1, max(.01, deadline - time.monotonic()))):
                    continue
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise ToolError("Local MCP process exited without a response")
                self.buffer.extend(chunk)
                if len(self.buffer) > 16_777_216:
                    raise ToolError("Local MCP response exceeds 16 MiB")
                continue
            line, _, remainder = self.buffer.partition(b"\n")
            self.buffer = remainder
            try:
                result = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(result, dict) or result.get("id") != request_id:
                continue
            if "error" in result:
                raise ToolError(f"Local MCP error: {result['error']}")
            return result.get("result", {})

    def call(self, name: str, arguments: dict, cancel: threading.Event):
        with self.lock:
            self.start(cancel)
            if name not in self.tools:
                raise ToolError(f"Local MCP tool unavailable: {name}")
            result = self._request("tools/call", {"name": name, "arguments": arguments}, cancel)
            if result.get("isError"):
                raise ToolError(f"Local MCP tool failed: {name}")
            structured = result.get("structuredContent")
            if structured is not None:
                if isinstance(structured, dict) and set(structured) == {"result"}:
                    structured = structured["result"]
                return _decode(structured)
            text = "\n".join(item.get("text", "") for item in result.get("content", [])
                if item.get("type") == "text")
            return _decode(text)

    def close(self) -> None:
        with self.lock:
            process, self.process = self.process, None
            if self.selector is not None:
                self.selector.close()
                self.selector = None
            self.tools.clear()
            self.buffer.clear()
            if process is not None:
                stop_process(process)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()


def _decode(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value
