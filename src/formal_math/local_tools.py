"""Local Lean acceptance, optional LSP goals, and local library retrieval.

No verification or retrieval is dispatched to a model-serving machine.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

from .mcp import MCPClient, ToolError, Cancelled, stop_process


def _environment() -> dict:
    env = os.environ.copy()
    env["PATH"] = str(Path.home() / ".elan/bin") + os.pathsep + env.get("PATH", "")
    return env


def _masked(code: str) -> str:
    """Mask nested comments and strings without changing line/column offsets."""
    result = list(code)
    i = depth = 0
    quoted = line = False
    while i < len(code):
        pair = code[i:i+2]
        if line:
            if code[i] == "\n":
                line = False
        elif depth:
            if pair == "/-":
                depth += 1
            elif pair == "-/":
                depth -= 1
                result[i:i+2] = "  "
                i += 2
                continue
        elif quoted:
            if code[i] == "\\":
                result[i:i+2] = " " * len(code[i:i+2])
                i += 2
                continue
            if code[i] == '"':
                quoted = False
                result[i] = " "
                i += 1
                continue
        elif pair == "--":
            line = True
        elif pair == "/-":
            depth = 1
        elif code[i] == '"':
            quoted = True
        else:
            i += 1
            continue
        if code[i] != "\n":
            result[i] = " "
        if pair == "/-" and depth and not line and not quoted:
            result[i:i+2] = "  "
            i += 2
        else:
            i += 1
    return "".join(result)


def _named_theorems(code: str) -> list[str]:
    names = []
    scopes = []
    commands = re.compile(r"(?m)^[ \t]*(?:@\[[^\]]*\]\s*)*(?:(?:private|protected|noncomputable)\s+)*(namespace|section|end|theorem|lemma)\b(?:[ \t]+([\w'.]+))?")
    for match in commands.finditer(_masked(code)):
        command, name = match.groups()
        if command in {"namespace", "section"}:
            scopes.append((command, name or ""))
        elif command == "end":
            if scopes:
                scopes.pop()
        elif name:
            if name.startswith("_root_."):
                names.append(name[7:])
            else:
                prefix = ".".join(value for kind, value in scopes if kind == "namespace" and value)
                names.append(prefix + "." + name if prefix else name)
    return names


def _feedback(diagnostics: str, goal: str, cap: int) -> tuple[str, str]:
    # One aggregate cap, not cap per diagnostic plus another cap for the goal.
    if len(goal) > cap:
        diagnostics = "[Complete goal state omitted: exceeds the feedback character cap.]\n" + diagnostics
        goal = ""  # Never present a cut hypothesis/goal as a complete proof state.
    unique = "\n".join(dict.fromkeys(line for line in diagnostics.splitlines() if line.strip()))
    selected_goal = goal
    remaining = max(0, cap - len(selected_goal))
    if len(unique) > remaining:
        marker = "\n[Diagnostic feedback truncated.]" if remaining >= 36 else "[...]"
        unique = (unique[:remaining - len(marker)] + marker) if remaining >= len(marker) else ""
    return unique, selected_goal


class LeanVerifier:
    def __init__(self, config: dict):
        self.settings = config.get("lean", {})
        self.project = Path(self.settings.get("project_path", "runtime/mathlib")).expanduser().resolve()
        self.timeout = float(self.settings.get("timeout_seconds", 240))
        self.feedback_chars = int(config.get("limits", {}).get("feedback_chars",
            self.settings.get("feedback_chars", 8000)))
        self.env = _environment()
        command = self.settings.get("lsp_command") or []
        self.lsp = MCPClient(command, cwd=self.project, env={**self.env,
            "LEAN_PROJECT_PATH": str(self.project), "LEAN_LSP_TEST_MODE": "1"},
            timeout=float(self.settings.get("lsp_timeout_seconds", 120))) if command else None

    def check(self, code: str, cancel: threading.Event) -> dict:
        if cancel.is_set():
            raise Cancelled("Run cancelled")
        plain = _masked(code)
        forbidden = re.search(r"\b(?:sorry|admit|axiom|constant|sorryAx|skipKernelTC|native_decide|unsafe|implemented_by)\b|#\s*(?:exit|eval|reduce)\b", plain)
        if forbidden:
            return {"valid": False, "available": True, "diagnostics":
                f"Unfinished proof or forbidden proof escape: {forbidden.group()}", "goal": ""}
        if not self.project.is_dir():
            return self._unavailable(f"Local Lean project is missing: {self.project}. Run scripts/setup-local.sh or configure lean.project_path.")
        command = list(self.settings.get("command", ["lake", "env", "lean"]))
        executable = shutil.which(command[0], path=self.env["PATH"]) if command else None
        if not executable:
            return self._unavailable("Local lake executable is unavailable. Install elan and prepare the Lean project.")
        command[0] = executable
        names = _named_theorems(code)
        if not names:
            return {"valid": False, "available": True, "diagnostics":
                "Use a named theorem or lemma for audited proof verification.", "goal": ""}
        scratch = self.project / ".formal_math"
        scratch.mkdir(exist_ok=True)
        path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".lean", prefix="proof-", dir=scratch,
                    encoding="utf-8", delete=False) as handle:
                path = Path(handle.name)
                audit = "\n".join("#print axioms " + name for name in names)
                handle.write(code + "\n\n" + audit + "\n")
            process = subprocess.Popen([*command, str(path)], cwd=self.project,
                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True)
            deadline = time.monotonic() + self.timeout
            while True:
                if cancel.is_set():
                    stop_process(process)
                    process.communicate()
                    raise Cancelled("Run cancelled")
                if time.monotonic() >= deadline:
                    stop_process(process)
                    process.communicate()
                    return self._unavailable(f"Local Lean verification timed out after {self.timeout:g}s")
                try:
                    output, _ = process.communicate(timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            diagnostics = output.decode("utf-8", errors="replace")
            clean = process.returncode == 0
            if clean:
                dependencies = re.findall(r"depends on axioms:\s*\[([^]]*)\]", diagnostics)
                allowed = {"propext", "Classical.choice", "Quot.sound"}
                unexpected = {item.strip() for block in dependencies for item in block.split(",")
                    if item.strip()} - allowed
                audits = len(dependencies) + len(re.findall(r"does not depend on any axioms", diagnostics))
                if unexpected or audits < len(names):
                    clean = False
                    diagnostics += "\nAxiom audit failed: " + (", ".join(sorted(unexpected)) or "missing audit output")
            goal = ""
            if not clean and self.lsp:
                # Inspection never grants acceptance. The completed local compiler above does.
                path.write_text(code, encoding="utf-8")
                try:
                    line_match = re.search(r"\.lean:(\d+):(\d+):", diagnostics)
                    line = int(line_match.group(1)) if line_match else max(1, len(code.splitlines()))
                    value = self.lsp.call("lean_goal", {"file_path": str(path), "line": line}, cancel)
                    goal = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                    if not goal.strip() or "no goals" in goal.lower():
                        goal = ""
                except Cancelled:
                    raise
                except ToolError as exc:
                    diagnostics += f"\nLocal goal inspection unavailable: {exc}"
            diagnostics, goal = _feedback(diagnostics, goal, self.feedback_chars)
            return {"valid": clean, "available": True, "diagnostics": diagnostics, "goal": goal}
        except OSError as exc:
            return self._unavailable(f"Local Lean verification failed: {exc}")
        finally:
            if self.lsp:
                self.lsp.close()  # Avoid retaining temporary LSP documents between checks.
            if path is not None:
                path.unlink(missing_ok=True)

    @staticmethod
    def _unavailable(message: str) -> dict:
        return {"valid": False, "available": False, "diagnostics": message, "goal": ""}

    def close(self) -> None:
        if self.lsp:
            self.lsp.close()


class LeanExplore:
    def __init__(self, config: dict):
        self.settings = config.get("retrieval", {})
        self.enabled = self.settings.get("enabled", True)
        env = _environment()
        env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "OPENAI_AGENTS_DISABLE_TRACING": "1", "CUDA_VISIBLE_DEVICES": "",
            "LEAN_EXPLORE_EMBEDDING_BATCH_SIZE": "1", "LEAN_EXPLORE_RERANKER_BATCH_SIZE": "1"})
        for config_key, environment_key in (("cache_dir", "LEAN_EXPLORE_CACHE_DIR"),
                ("hf_cache_dir", "HF_HOME"), ("data_version", "LEAN_EXPLORE_VERSION")):
            if self.settings.get(config_key):
                env[environment_key] = str(self.settings[config_key])
        command = self.settings.get("command") or ["runtime/lean-explore/.venv/bin/lean-explore",
            "mcp", "serve", "--backend", "local"]
        self.client = MCPClient(command, env=env,
            timeout=float(self.settings.get("timeout_seconds", 600)))
        self.sources: dict[int, str | None] = {}

    def retrieve(self, query: str, cancel: threading.Event) -> list[dict]:
        if not self.enabled:
            return []
        if cancel.is_set():
            raise Cancelled("Run cancelled")
        summary = self.client.call("search_summary", {"query": query[:int(self.settings.get("max_query_chars", 4000))],
            "limit": int(self.settings.get("limit", 12)),
            "rerank_top": int(self.settings.get("rerank_top", 0)),
            "packages": self.settings.get("packages", ["Mathlib", "Init"])}, cancel)
        if not isinstance(summary, dict) or not isinstance(summary.get("results"), list):
            raise ToolError("LeanExplore returned an invalid search result")
        hits = []
        for index, raw in enumerate(summary["results"][:int(self.settings.get("limit", 12))]):
            declaration_id = int(raw["id"])
            source = None
            if index < int(self.settings.get("source_limit", 4)):
                if declaration_id not in self.sources:
                    value = self.client.call("get_source_code", {"declaration_id": declaration_id}, cancel)
                    self.sources[declaration_id] = value.get("source_text") if isinstance(value, dict) else None
                source = self.sources[declaration_id]
            hits.append({"declaration_id": declaration_id, "exact_name": str(raw.get("name", "")),
                "lean_source": source, "description": raw.get("description"),
                "data_version": self.settings.get("data_version")})
        return hits

    def close(self) -> None:
        self.client.close()
