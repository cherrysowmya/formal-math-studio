"""Configuration for local orchestration and independently routed model roles."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tomllib
from urllib.parse import urlparse

from .credentials import ENV_NAME, api_keys


ROLES = (
    "formal_initial", "formal_reviser", "informal_generator",
    "informal_reviewer", "discussion", "fresh_formal",
)


def _role(provider: str, model: str, inputs: int, outputs: int, context: int,
          temperature: float = 0.6, thinking: bool = True) -> dict:
    return dict(provider=provider, model=model, input_tokens=inputs,
                output_tokens=outputs, context_tokens=context,
                temperature=temperature, top_p=0.95, thinking=thinking)


def defaults() -> dict:
    model = "claude-sonnet-5-5"
    return {
        "app": {"host": "127.0.0.1", "port": 8765, "output_dir": "runtime/outputs",
                "env_file": str(Path.cwd() / ".env"),
                "max_concurrent_runs": 1},
        "providers": {
            "openrouter": {"kind": "chat_completions", "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY", "timeout_seconds": 600},
            "deepseek": {"kind": "chat_completions", "base_url": "https://api.deepseek.com", "api_key_env": "DEEPSEEK_API_KEY", "timeout_seconds": 600},
            "groq": {"kind": "chat_completions", "base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY", "timeout_seconds": 600},
            "openai": {"kind": "openai", "base_url": "https://api.openai.com/v1",
                       "api_key_env": "OPENAI_API_KEY", "timeout_seconds": 600},
            "anthropic": {"kind": "anthropic", "base_url": "https://api.anthropic.com/v1",
                          "api_key_env": "ANTHROPIC_API_KEY", "timeout_seconds": 600,
                          "thinking_mode": "adaptive"},
        },
        "roles": {
            "formal_initial": _role("anthropic", model, 8192, 32000, 40960, 1.0),
            "formal_reviser": _role("anthropic", model, 12288, 24576, 40960, 1.0),
            "informal_generator": _role("anthropic", model, 8192, 16384, 32768),
            "informal_reviewer": _role("anthropic", model, 12288, 8192, 32768),
            "discussion": _role("anthropic", model, 12288, 12288, 32768),
            "fresh_formal": _role("anthropic", model, 8192, 32000, 40960, 1.0),
        },
        "limits": {
            "max_formal_attempts": 5, "max_informal_rounds": 3,
            "informal_after_failures": 1, "discussion_after_failures": 2,
            "max_input_bytes": 262144, "max_run_seconds": 7200,
            "feedback_chars": 8000, "failure_chars": 6000,
            "failure_pairs": 2, "outline_chars": 6000, "critique_chars": 4000,
            "informal_packet_chars": 16000,
        },
        "retrieval": {
            "enabled": True, "required": True,
            "command": ["lean-explore", "mcp", "serve", "--backend", "local"],
            "cache_dir": "runtime/lean-explore/cache", "hf_cache_dir": "runtime/huggingface",
            "data_version": "20260714_172516", "packages": ["Mathlib", "Init"],
            "limit": 12, "source_limit": 4, "rerank_top": 0,
            "max_task_queries": 5, "max_outline_queries": 2, "max_queries": 7,
            "max_query_chars": 4000, "outline_query_chars": 240,
            "timeout_seconds": 600,
            "formal_chars": 12000, "discussion_chars": 6000,
            "fresh_chars": 8000, "informal_chars": 4000,
        },
        "lean": {
            "project_path": "runtime/mathlib", "command": ["lake", "env", "lean"],
            "lsp_command": ["lean-lsp-mcp"], "timeout_seconds": 240, "lsp_timeout_seconds": 120,
        },
    }


def _merge(target: dict, updates: dict, prefix: str = "") -> None:
    for key, value in updates.items():
        label = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            if key not in target:
                target[key] = {}
            if not isinstance(target[key], dict):
                raise ValueError(f"{label} must be a table")
            _merge(target[key], value, label)
        else:
            target[key] = value


def validate(config: dict) -> None:
    for section in ("app", "providers", "roles", "limits", "retrieval", "lean"):
        if not isinstance(config.get(section), dict):
            raise ValueError(f"{section} must be a table")
    for name, provider in config["providers"].items():
        if not isinstance(provider, dict) or provider.get("kind") not in {"openai", "anthropic", "openai_compatible", "chat_completions"}:
            raise ValueError(f"Invalid provider {name}")
        parsed = urlparse(provider.get("base_url", ""))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError(f"Provider {name} needs an HTTP(S) URL without embedded credentials")
        if "api_key" in provider:
            raise ValueError("Use api_key_env; do not store API keys in configuration")
        variable = provider.get("api_key_env", "")
        if not isinstance(variable, str) or (variable and not ENV_NAME.fullmatch(variable)):
            raise ValueError(f"Invalid API-key environment variable for {name}")
        if not isinstance(provider.get("timeout_seconds", 600), (int, float)) or provider.get("timeout_seconds", 600) <= 0:
            raise ValueError(f"Invalid timeout for {name}")
    if set(config["roles"]) != set(ROLES):
        raise ValueError("Configuration must contain exactly the six supported model roles")
    for name, role in config["roles"].items():
        if role.get("provider") not in config["providers"]:
            raise ValueError(f"Unknown provider for {name}")
        if not isinstance(role.get("model"), str) or not role["model"].strip() or len(role["model"]) > 256:
            raise ValueError(f"Invalid model for {name}")
        for key in ("input_tokens", "output_tokens", "context_tokens"):
            if type(role.get(key)) is not int or role[key] <= 0:
                raise ValueError(f"{name}.{key} must be a positive integer")
        if role["input_tokens"] + role["output_tokens"] > role["context_tokens"]:
            raise ValueError(f"{name}: input plus output exceeds the configured context")
        if not 0 <= role.get("temperature", 0.6) <= 2 or not 0 < role.get("top_p", .95) <= 1:
            raise ValueError(f"Invalid sampling parameters for {name}")
        if type(role.get("thinking", True)) is not bool:
            raise ValueError(f"{name}.thinking must be boolean")
    for key, value in config["limits"].items():
        if type(value) is not int or value <= 0:
            raise ValueError(f"limits.{key} must be a positive integer")
    if config["limits"]["max_formal_attempts"] > 20 or config["limits"]["max_informal_rounds"] > 5:
        raise ValueError("Too many formal attempts or informal refinement rounds")
    r = config["retrieval"]
    if any(type(r[k]) is not int or r[k] <= 0 for k in (
        "limit", "source_limit", "max_task_queries", "max_outline_queries", "max_queries",
        "max_query_chars", "outline_query_chars", "formal_chars", "discussion_chars", "fresh_chars", "informal_chars")):
        raise ValueError("Retrieval counts and character limits must be positive integers")
    if r["source_limit"] > r["limit"]:
        raise ValueError("Retrieval source_limit cannot exceed limit")
    if type(r["enabled"]) is not bool or type(r["required"]) is not bool:
        raise ValueError("Retrieval enabled/required must be boolean")
    if type(r["rerank_top"]) is not int or r["rerank_top"] < 0:
        raise ValueError("rerank_top must be a nonnegative integer")
    for label, command in (("lean.command", config["lean"]["command"]),
                           ("lean.lsp_command", config["lean"]["lsp_command"]),
                           ("retrieval.command", r["command"])):
        if not isinstance(command, list) or any(not isinstance(v, str) or not v for v in command):
            raise ValueError(f"{label} must be an argument array")
        if label != "lean.lsp_command" and not command:
            raise ValueError(f"{label} cannot be empty")
    if type(config["app"]["port"]) is not int or not 1 <= config["app"]["port"] <= 65535:
        raise ValueError("Invalid local server port")
    if config["app"]["host"] not in {"127.0.0.1", "localhost"}:
        raise ValueError("The local web interface must bind to loopback")
    if type(config["app"]["max_concurrent_runs"]) is not int or not 1 <= config["app"]["max_concurrent_runs"] <= 4:
        raise ValueError("max_concurrent_runs must be between 1 and 4")
    env_file = config["app"].get("env_file", "")
    if not isinstance(env_file, str) or Path(env_file).name != ".env":
        raise ValueError("app.env_file must point to a local file named .env")
    for key in ("timeout_seconds", "lsp_timeout_seconds"):
        if not isinstance(config["lean"][key], (int, float)) or config["lean"][key] <= 0:
            raise ValueError(f"lean.{key} must be positive")


def load_config(path: str | Path | None = None) -> dict:
    config = defaults()
    base = Path.cwd()
    if path is not None:
        config_path = Path(path).expanduser().resolve()
        with config_path.open("rb") as handle:
            _merge(config, tomllib.load(handle))
        base = config_path.parent
    for section, key in (("app", "output_dir"), ("app", "env_file"), ("lean", "project_path"),
                         ("retrieval", "cache_dir"), ("retrieval", "hf_cache_dir")):
        value = Path(config[section][key]).expanduser()
        value = value if value.is_absolute() else base / value
        # Keep the final .env path intact so credential storage can reject symlinks.
        config[section][key] = str(value.absolute() if key == "env_file" else value.resolve())
    from .provider_settings import load_providers
    load_providers(config)
    validate(config)
    return config


def public_config(config: dict) -> dict:
    """Expose configuration metadata, never environment values or secret fields."""
    credentials = api_keys(config)
    return {
        "roles": {name: {key: deepcopy(role[key]) for key in (
            "provider", "model", "input_tokens", "output_tokens", "context_tokens",
            "temperature", "top_p", "thinking")}
                  for name, role in config["roles"].items()},
        "providers": {name: {"kind": p["kind"], "base_url": p["base_url"],
                             "key_configured": bool(credentials[name][0]),
                             "key_source": credentials[name][1],
                             "key_editable": bool(p.get("api_key_env"))}
                      for name, p in config["providers"].items()},
        "limits": deepcopy(config["limits"]),
        "retrieval": {k: deepcopy(v) for k, v in config["retrieval"].items()
                      if k not in {"command", "cache_dir", "hf_cache_dir"}},
    }


def apply_overrides(config: dict, overrides: dict | None) -> dict:
    result = deepcopy(config)
    if overrides is None:
        return result
    if not isinstance(overrides, dict) or any(key not in ROLES for key in overrides):
        raise ValueError("Only supported role overrides are allowed")
    for name, value in overrides.items():
        if not isinstance(value, dict) or not set(value) <= {"provider", "model"}:
            raise ValueError("Browser overrides may only change a role's provider and model")
        result["roles"][name].update(value)
    validate(result)
    return result
