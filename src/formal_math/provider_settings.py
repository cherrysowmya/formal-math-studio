"""User-added API connections; credentials stay separately in .env."""
from copy import deepcopy
import json
import re
import threading
from urllib.parse import urlsplit

from .credentials import env_path, _atomic_write, _read

_lock = threading.RLock()
KINDS = {"chat_completions", "anthropic", "openai", "openai_compatible"}


def _path(config):
    return env_path(config).parent / "providers.local.json"


def _provider(name, value):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name):
        raise ValueError("Provider name must start with a lowercase letter and contain only letters, digits or underscores")
    if not isinstance(value, dict) or set(value) != {"kind", "base_url"} or value["kind"] not in KINDS:
        raise ValueError("Choose a supported API protocol and base URL")
    url = value["base_url"]
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() for c in url):
        raise ValueError("Enter a valid API base URL")
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError("API URLs must use HTTP(S), without credentials, query parameters or fragments")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote API providers require HTTPS; HTTP is allowed for loopback servers")
    return {"kind": value["kind"], "base_url": url.rstrip("/"),
            "api_key_env": "CUSTOM_" + name.upper() + "_API_KEY", "timeout_seconds": 600}


def load_providers(config):
    saved = json.loads(_read(_path(config)) or "{}")
    if not isinstance(saved, dict):
        raise ValueError("Local providers must be a JSON object")
    for name, value in saved.items():
        if name in config["providers"]:
            raise ValueError("A saved custom provider conflicts with an existing provider")
        config["providers"][name] = _provider(name, value)


def add_provider(config, data):
    if not isinstance(data, dict) or set(data) != {"name", "kind", "base_url"}:
        raise ValueError("Supply a provider name, API protocol and base URL")
    name = data["name"]
    value = {key: data[key] for key in ("kind", "base_url")}
    provider = _provider(name, value)
    with _lock:
        if name in config["providers"]:
            raise ValueError("That provider name already exists; choose a different name")
        saved = json.loads(_read(_path(config)) or "{}")
        saved[name] = value
        candidate = deepcopy(config)
        candidate["providers"][name] = provider
        from .config import validate
        validate(candidate)
        _atomic_write(_path(config), json.dumps(saved, indent=2) + "\n", 0o600)
        config["providers"] = {**config["providers"], name: provider}
