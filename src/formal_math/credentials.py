"""Local API-key storage. Dotenv values are data and are never executed."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import threading


ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
ASSIGNMENT = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)")
IGNORE_RULES = "# Local API credentials\n.env\n.env.*\n!.env.example\n"
_lock = threading.RLock()


def env_path(config: dict) -> Path:
    return Path(config["app"].get("env_file", Path.cwd() / ".env")).absolute()


def _read(path: Path) -> str:
    if path.is_symlink():
        raise ValueError("Local credential files must not be symbolic links")
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _parse(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        match = ASSIGNMENT.fullmatch(line)
        if not match:
            continue
        name, value = match.groups()
        value = value.strip()
        if value.startswith('"'):
            encoded = value
            try:
                value, end = json.JSONDecoder().raw_decode(encoded)
            except ValueError:
                continue
            tail = encoded[end:].strip()
            if not isinstance(value, str) or (tail and not tail.startswith("#")):
                continue
        elif value.startswith("'"):
            end = value.find("'", 1)
            tail = value[end + 1:].strip() if end >= 0 else ""
            if end < 0 or (tail and not tail.startswith("#")):
                continue
            value = value[1:end]
        else:
            value = value.split(" #", 1)[0].strip()
        values[name] = value
    return values


def api_keys(config: dict) -> dict[str, tuple[str, str | None]]:
    """Read only configured API-key variables, with .env taking precedence."""
    with _lock:
        saved = _parse(_read(env_path(config)))
    result = {}
    for name, provider in config["providers"].items():
        variable = provider.get("api_key_env", "")
        if variable and saved.get(variable):
            result[name] = (saved[variable], ".env")
        elif variable and os.environ.get(variable):
            result[name] = (os.environ[variable], "environment")
        else:
            result[name] = ("", None)
    return result


def _atomic_write(path: Path, content: str, mode: int) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f"{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_api_keys(config: dict, updates: dict) -> None:
    """Persist provider-key updates without returning keys or changing os.environ.

    Missing providers are unchanged; null removes a saved key. Exported shell
    keys remain available as a fallback. Each run snapshots its own credentials.
    """
    if not isinstance(updates, dict):
        raise ValueError("api_keys must be an object of provider names and keys")
    changes = {}
    for name, value in updates.items():
        provider = config["providers"].get(name)
        if provider is None:
            raise ValueError("Unknown credential provider")
        variable = provider.get("api_key_env", "")
        if not ENV_NAME.fullmatch(variable):
            raise ValueError("This provider has no API-key variable configured")
        if value is not None and (not isinstance(value, str) or not value or len(value) > 8192
                                  or any(not 33 <= ord(c) <= 126 for c in value)):
            raise ValueError("API keys must be nonempty text without spaces or control characters")
        if variable in changes and changes[variable] != value:
            raise ValueError("Providers sharing an API-key variable must use the same key")
        changes[variable] = value
    if not changes:
        return
    with _lock:
        path = env_path(config)
        existing = _read(path)
        lines, seen = [], set()
        for line in existing.splitlines(keepends=True):
            match = ASSIGNMENT.fullmatch(line.rstrip("\r\n"))
            name = match[1] if match else None
            if name not in changes:
                lines.append(line)
            elif name not in seen:
                if changes[name] is not None:
                    lines.append(f"{name}={json.dumps(changes[name])}\n")
                seen.add(name)
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.extend(f"{name}={json.dumps(value)}\n" for name, value in changes.items()
                     if name not in seen and value is not None)
        ignore_path = path.parent / ".gitignore"
        ignore = _read(ignore_path)
        # Put the rules last so an earlier negation cannot expose credentials.
        if not ignore.endswith(IGNORE_RULES):
            _atomic_write(ignore_path, ignore.rstrip("\n") + "\n\n" + IGNORE_RULES, 0o644)
        _atomic_write(path, "".join(lines), 0o600)
