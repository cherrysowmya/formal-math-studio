"""Loopback-only web application; no cloud hosting or browser-side credentials."""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from uuid import uuid4

from .config import apply_overrides, public_config
from .engine import solve
from .local_tools import LeanExplore, LeanVerifier
from .providers import ModelGateway


TERMINAL = {"verified", "unverified", "failed", "cancelled"}


class RunStore:
    def __init__(self, config: dict, solver=solve, tool_factory=None):
        self.config, self.solver, self.tool_factory = config, solver, tool_factory
        self.lock = threading.RLock()
        self.runs: dict[str, dict] = {}
        self.active = threading.Semaphore(config.get("app", {}).get("max_concurrent_runs", 1))
        self.output_dir = Path(config.get("app", {}).get("output_dir", "outputs")).resolve()

    def start(self, code, filename, overrides=None):
        if not isinstance(code, str) or not code.strip():
            raise ValueError("Enter or upload Lean code first")
        if len(code.encode()) > self.config["limits"].get("max_input_bytes", 262144):
            raise ValueError("Lean file exceeds the configured upload size")
        config = apply_overrides(self.config, overrides or {})
        if not self.active.acquire(blocking=False):
            raise BlockingIOError("A local run is still active. Wait for it to finish before starting another.")
        run_id = uuid4().hex
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(str(filename or "proof.lean")).name)[:120]
        name = (name[:-5] if name.endswith(".lean") else name) or "proof"
        record = {"id": run_id, "status": "queued", "code": code, "verified": False,
                  "filename": name + "_output.lean", "error": None,
                  "download_url": f"/api/runs/{run_id}/download", "events": [], "usage": {},
                  "cancel": threading.Event(), "path": None}
        with self.lock:
            # Bound browser history in memory. Output files remain available locally.
            for old in list(self.runs):
                if len(self.runs) < 32:
                    break
                if self.runs[old]["status"] in TERMINAL:
                    del self.runs[old]
            self.runs[run_id] = record
        thread = threading.Thread(target=self._work, args=(record, config), daemon=True, name=f"proof-{run_id[:8]}")
        thread.start()
        return {"id": run_id, "status": "queued"}

    def get(self, run_id):
        with self.lock:
            record = self.runs[run_id]
            return {key: value for key, value in record.items() if key not in {"cancel", "path"}}

    def cancel(self, run_id):
        with self.lock:
            record = self.runs[run_id]
            if record["status"] not in TERMINAL:
                record["cancel"].set()
                record["status"] = "cancelled"
                record["verified"] = False
                record["error"] = "Cancellation requested. An in-flight model request may still finish remotely."
        return self.get(run_id)

    def _work(self, record, config):
        verifier = retriever = None
        def emit(role, message, kind="info"):
            with self.lock:
                if len(record["events"]) < 2000:
                    record["events"].append({"seq": len(record["events"]) + 1, "time": time.time(),
                                             "role": str(role), "message": str(message)[:3000], "kind": str(kind)})
        timer = threading.Timer(config["limits"].get("max_run_seconds", 7200), record["cancel"].set)
        timer.daemon = True
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            directory = self.output_dir / record["id"]
            directory.mkdir(mode=0o700)
            (directory / "input.lean").write_text(record["code"], encoding="utf-8")
            with self.lock:
                if record["cancel"].is_set():
                    raise InterruptedError("Run cancelled before starting")
                record["status"] = "running"
            timer.start()
            if self.tool_factory:
                verifier, retriever = self.tool_factory(config)
            else:
                verifier, retriever = LeanVerifier(config), LeanExplore(config)
            gateway = ModelGateway(config, emit, record["cancel"])
            result = self.solver(record["code"], config, gateway.chat, verifier, retriever, emit, record["cancel"])
            code = result.get("code") or record["code"]
            if record["cancel"].is_set():
                result.update(status="cancelled", verified=False, error="Run cancelled or its time limit was reached")
            elif result.get("verified") is not True:
                result["verified"] = False
                if result.get("status") == "verified":
                    result["status"] = "unverified"
            path = directory / record["filename"]
            path.write_text(code, encoding="utf-8")
            with self.lock:
                # Cancellation and promotion to verified must be atomic. A
                # cancellation can arrive while the output file is being saved.
                if record["cancel"].is_set():
                    result.update(status="cancelled", verified=False, error="Run cancelled or its time limit was reached")
                record.update({"status": result.get("status", "unverified"), "code": code,
                               "verified": result["verified"], "error": result.get("error"),
                               "usage": result.get("usage", {}), "path": path})
            (directory / "result.json").write_text(json.dumps(self.get(record["id"]), indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            # Expected adapter errors contain no credentials. Redact environment
            # secrets even if a third-party verifier error accidentally includes one.
            message = str(exc)
            import os
            for provider in config["providers"].values():
                secret = os.environ.get(provider.get("api_key_env", ""), "")
                if secret:
                    message = message.replace(secret, "[redacted]")
            emit("system", message, "error")
            with self.lock:
                record.update(status="cancelled" if record["cancel"].is_set() else "failed", verified=False, error=message[:2000])
            try:
                directory = self.output_dir / record["id"]
                path = directory / record["filename"]
                path.write_text(record["code"], encoding="utf-8")
                record["path"] = path
                (directory / "result.json").write_text(json.dumps(self.get(record["id"]), indent=2, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        finally:
            timer.cancel()
            for tool in (verifier, retriever):
                if tool is not None:
                    try:
                        tool.close()
                    except Exception:
                        pass
            self.active.release()


def create_server(config, host="127.0.0.1", port=8765, store=None):
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("This local application binds only to loopback (127.0.0.1)")
    runs = store or RunStore(config)
    static = Path(__file__).parent / "static"

    class Handler(BaseHTTPRequestHandler):
        server_version = "FormalMathStudio"

        def log_message(self, fmt, *args):
            # Local request paths only, no credentials or source code.
            return

        def _send(self, status, data, content_type="application/json; charset=utf-8", headers=None):
            raw = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)

        def _trusted(self):
            expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in expected:
                self._send(403, {"error": "Only the local application host is accepted"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + h for h in expected}:
                self._send(403, {"error": "Cross-origin requests are not allowed"})
                return False
            return True

        def do_GET(self):
            if not self._trusted():
                return
            path = urlsplit(self.path).path
            if path == "/api/config":
                self._send(200, public_config(config))
            elif path == "/api/health":
                self._send(200, {"status": "ok", "local_only": True})
            elif match := re.fullmatch(r"/api/runs/([0-9a-f]{32})(/download)?", path):
                try:
                    result = runs.get(match[1])
                    if match[2]:
                        if result["status"] not in TERMINAL:
                            self._send(409, {"error": "Output is available when the run ends"})
                        else:
                            self._send(200, result["code"].encode(), "text/plain; charset=utf-8",
                                       {"Content-Disposition": f'attachment; filename="{result["filename"]}"',
                                        "X-Proof-Verified": str(result["verified"]).lower()})
                    else:
                        self._send(200, result)
                except KeyError:
                    self._send(404, {"error": "Run not found in this server session"})
            else:
                name = "index.html" if path == "/" else path.lstrip("/")
                file = static / name
                if name not in {"index.html", "app.js", "styles.css", "favicon.svg"} or not file.is_file():
                    self._send(404, {"error": "Not found"})
                else:
                    self._send(200, file.read_bytes(), (mimetypes.guess_type(name)[0] or "application/octet-stream") + "; charset=utf-8")

        def do_POST(self):
            if not self._trusted():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = config["limits"].get("max_input_bytes", 262144) * 7 + 65536
                if length < 0 or length > limit:
                    self._send(413, {"error": "Request is too large"})
                    return
                if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                    self._send(415, {"error": "Use application/json"})
                    return
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")
                path = urlsplit(self.path).path
                if path == "/api/runs":
                    if set(data) - {"code", "filename", "role_overrides"}:
                        raise ValueError("Unsupported run settings")
                    self._send(202, runs.start(data.get("code"), data.get("filename"), data.get("role_overrides")))
                elif match := re.fullmatch(r"/api/runs/([0-9a-f]{32})/cancel", path):
                    self._send(200, runs.cancel(match[1]))
                else:
                    self._send(404, {"error": "Not found"})
            except KeyError:
                self._send(404, {"error": "Unknown run or provider"})
            except BlockingIOError as exc:
                self._send(409, {"error": str(exc)})
            except (ValueError, TypeError) as exc:
                self._send(400, {"error": str(exc)})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.run_store = runs
    return server
