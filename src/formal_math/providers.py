"""Server-side provider adapters. Credentials never pass through the browser.

Counts come from the same service/model that generates the answer. There is no
character-based fallback when the provider cannot count the rendered request.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable


class ProviderError(RuntimeError):
    pass


class BudgetError(ProviderError):
    pass


def _request(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ProviderError("Model service response exceeds the supported size")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ProviderError("Model service returned a non-object JSON response")
            return result
    except urllib.error.HTTPError as exc:
        # Never echo request headers, bodies or upstream diagnostic dumps.
        raise ProviderError(f"Model service returned HTTP {exc.code}; check its model, credentials and limits") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or "configured-host"
        authority = f"[{host}]" if ":" in host else host
        if parsed.port:
            authority += f":{parsed.port}"
        endpoint = f"{parsed.scheme}://{authority}"
        if host in {"localhost", "127.0.0.1", "::1"}:
            guidance = "Start the configured model server or its SSH tunnel; starting the web app alone does not start inference."
        else:
            guidance = "Check the API connection and provider endpoint."
        # Do not include URL credentials, query strings or raw exception text.
        raise ProviderError(f"Cannot reach model endpoint {endpoint} ({type(exc).__name__}). {guidance}") from None
    except (ValueError, UnicodeError):
        raise ProviderError("Model service returned invalid JSON") from None


def _without_thinking(text: str) -> str:
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    if "<think>" in text:
        return ""
    return text.strip()


class ModelGateway:
    def __init__(self, config: dict, emit: Callable, cancel: threading.Event):
        self.config, self.emit, self.cancel = config, emit, cancel

    def _connection(self, role: str):
        spec = self.config["roles"][role]
        provider = self.config["providers"][spec["provider"]]
        base = provider["base_url"].rstrip("/")
        if urllib.parse.urlsplit(base).scheme not in {"http", "https"}:
            raise ProviderError("Provider base_url must be an HTTP(S) URL")
        key_env = provider.get("api_key_env", "")
        key = os.environ.get(key_env, "") if key_env else ""
        if provider["kind"] in {"openai", "anthropic"} and not key:
            raise ProviderError(f"Set {key_env or 'the provider API key environment variable'} in the local server shell")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        if provider["kind"] == "anthropic":
            headers = {"x-api-key": key, "anthropic-version": provider.get("api_version", "2023-06-01")}
        return spec, provider, base, headers

    @staticmethod
    def _claude(messages):
        system = "\n\n".join(m["content"] for m in messages if m["role"] in {"system", "developer"})
        body = [m for m in messages if m["role"] not in {"system", "developer"}]
        return system, body

    @staticmethod
    def _claude_thinking(spec, provider):
        if not spec.get("thinking", True):
            return None
        if provider.get("thinking_mode", "enabled") == "adaptive":
            return {"type": "adaptive"}
        return {"type": "enabled", "budget_tokens": min(spec["output_tokens"] - 1024, max(1024, spec["output_tokens"] // 2))}

    def _count(self, spec, provider, base, headers, messages) -> int:
        if self.cancel.is_set():
            raise InterruptedError("Run cancelled")
        kind = provider["kind"]
        if kind == "openai":
            payload = {"model": spec["model"], "input": messages}
            path = provider.get("count_tokens_path") or "/responses/input_tokens"
            result = _request(base + path, payload, headers, min(provider.get("timeout_seconds", 600), 60))
            value = result.get("input_tokens")
        elif kind == "anthropic":
            system, body = self._claude(messages)
            payload = {"model": spec["model"], "system": system, "messages": body}
            thinking = self._claude_thinking(spec, provider)
            if thinking:
                payload["thinking"] = thinking
            result = _request(base + "/messages/count_tokens", payload,
                              headers, min(provider.get("timeout_seconds", 600), 60))
            value = result.get("input_tokens")
        else:
            origin = base[:-3] if base.endswith("/v1") else base
            payload = {"model": spec["model"], "messages": messages, "add_generation_prompt": True,
                       "chat_template_kwargs": {**provider.get("chat_template_kwargs", {}), "enable_thinking": spec.get("thinking", True)}}
            result = _request(origin + (provider.get("count_tokens_path") or "/tokenize"), payload, headers,
                              min(provider.get("timeout_seconds", 600), 60))
            value = result.get("count")
        if type(value) is not int or value < 0:
            raise ProviderError("Provider token-count endpoint returned no valid count; generation was not sent")
        return value

    @staticmethod
    def _trim(messages) -> str | None:
        try:
            packet = json.loads(messages[-1]["content"])
        except (ValueError, KeyError, IndexError):
            return None
        if not isinstance(packet, dict):
            return None
        for key in ("retrieved_declarations", "failure_history", "discussion", "review", "informal_outline"):
            value = packet.get(key)
            if not value:
                continue
            if isinstance(value, list):
                value.pop(0 if key == "failure_history" else -1)
            else:
                packet.pop(key)
            messages[-1]["content"] = json.dumps(packet, ensure_ascii=False)
            return key
        return None

    def chat(self, role: str, messages: list[dict]) -> dict:
        spec, provider, base, headers = self._connection(role)
        self.emit(role, f"Connecting to {spec['provider']} using {spec['model']}", "info")
        messages = copy.deepcopy(messages)
        removed = set()
        while True:
            count = self._count(spec, provider, base, headers, messages)
            if count <= spec["input_tokens"] and count + spec["output_tokens"] <= spec["context_tokens"]:
                break
            field = self._trim(messages)
            if field is None:
                raise BudgetError(f"{role}: immutable task, goal and candidate exceed the input budget ({count} tokens)")
            removed.add(field)
        if removed:
            self.emit(role, "Trimmed optional context to fit the model input budget: " + ", ".join(sorted(removed)), "info")
        if self.cancel.is_set():
            raise InterruptedError("Run cancelled")
        kind = provider["kind"]
        if kind == "openai":
            payload = {"model": spec["model"], "input": messages, "max_output_tokens": spec["output_tokens"], "store": False}
            if provider.get("reasoning_effort"):
                payload["reasoning"] = {"effort": provider["reasoning_effort"]}
            if provider.get("send_sampling", False):
                payload.update(temperature=spec.get("temperature", 1), top_p=spec.get("top_p", .95))
            response = _request(base + "/responses", payload, headers, provider.get("timeout_seconds", 600))
            content = "\n".join(c.get("text", "") for item in response.get("output", [])
                                if item.get("type") == "message" for c in item.get("content", []) if c.get("type") == "output_text")
            usage = response.get("usage", {})
            finish = "length" if response.get("status") == "incomplete" else "stop"
            if response.get("status") in {"failed", "cancelled"}:
                raise ProviderError("OpenAI did not complete the generation")
            output_count = usage.get("output_tokens", 0)
        elif kind == "anthropic":
            system, body = self._claude(messages)
            payload = {"model": spec["model"], "system": system, "messages": body, "max_tokens": spec["output_tokens"]}
            thinking = self._claude_thinking(spec, provider)
            if thinking:
                payload["thinking"] = thinking
                if thinking["type"] == "enabled":
                    payload["temperature"] = 1
            else:
                payload["temperature"] = spec.get("temperature", 1)
            response = _request(base + "/messages", payload, headers, provider.get("timeout_seconds", 600))
            content = "\n".join(c.get("text", "") for c in response.get("content", []) if c.get("type") == "text")
            finish = "length" if response.get("stop_reason") == "max_tokens" else "stop"
            output_count = response.get("usage", {}).get("output_tokens", 0)
        else:
            payload = {"model": spec["model"], "messages": messages, "max_tokens": spec["output_tokens"],
                       "temperature": spec.get("temperature", 1), "top_p": spec.get("top_p", .95), "stream": False,
                       "chat_template_kwargs": {**provider.get("chat_template_kwargs", {}), "enable_thinking": spec.get("thinking", True)}}
            response = _request(base + "/chat/completions", payload, headers, provider.get("timeout_seconds", 600))
            choices = response.get("choices", [])
            if not choices:
                raise ProviderError("Model returned no completion choices")
            content = choices[0].get("message", {}).get("content") or ""
            finish = choices[0].get("finish_reason", "stop")
            output_count = response.get("usage", {}).get("completion_tokens", 0)
        if self.cancel.is_set():
            raise InterruptedError("Run cancelled")
        if not isinstance(content, str):
            raise ProviderError("Model returned unsupported content")
        content = _without_thinking(content)
        if not content and finish != "length":
            raise ProviderError("Model returned no public answer")
        return {"text": content, "input_tokens": count, "output_tokens": int(output_count), "finish_reason": finish}
