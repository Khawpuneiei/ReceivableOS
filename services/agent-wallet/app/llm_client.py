"""Thin, pluggable LLM client (root CLAUDE.md: `complete(messages, schema)`). Owner: Agent AI engineer.

Used only by the agent loop (`app/agent/`) to pick a lender quote. When this returns None the deterministic
picker does the same job, so the demo runs offline (root CLAUDE.md DoD #5). Same shape as policy-ai's client.

Reads LLM_PROVIDER (none | anthropic | openai), LLM_MODEL and LLM_API_KEY from the environment. Returns
None, meaning "use the deterministic fallback", when the provider is none or unknown, the key or model is
missing, the key is the .env.example placeholder, or on a timeout, any error or a reply that isn't a JSON
object. Calls go over the standard library's HTTP client, so no vendor SDK is needed.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

log = logging.getLogger("agent-wallet")

TIMEOUT_SECONDS = 5
MAX_TOKENS = 300
PLACEHOLDER_KEYS = {"", "replace-me", "changeme", "your-key-here"}
_ENDPOINTS = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "openai": "https://api.openai.com/v1/chat/completions",
}


def settings() -> tuple[str, str, str] | None:
    """(provider, model, key) when a real LLM is configured, else None."""
    provider = os.environ.get("LLM_PROVIDER", "none").strip().lower()
    model = os.environ.get("LLM_MODEL", "").strip()
    key = os.environ.get("LLM_API_KEY", "").strip()
    if (
        provider not in _ENDPOINTS
        or not model
        or key.lower() in PLACEHOLDER_KEYS
        or key.lower().startswith("replace")
    ):
        return None
    return provider, model, key


def _request(
    provider: str, model: str, key: str, messages: list[dict], schema: dict
) -> urllib.request.Request:
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    system += "\nReply with one JSON object only, matching this JSON schema:\n" + json.dumps(schema)
    chat = [m for m in messages if m["role"] != "system"]
    if provider == "anthropic":
        body = {"model": model, "max_tokens": MAX_TOKENS, "system": system, "messages": chat}
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        body = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "system", "content": system}, *chat],
            "response_format": {"type": "json_object"},
        }
        headers = {"authorization": f"Bearer {key}"}
    return urllib.request.Request(
        _ENDPOINTS[provider],
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )


def _text(provider: str, reply: dict) -> str:
    if provider == "anthropic":
        return "".join(
            part.get("text", "") for part in reply.get("content", []) if part.get("type") == "text"
        )
    return reply["choices"][0]["message"]["content"]


def _json_object(text: str) -> dict | None:
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def complete(messages: list[dict[str, str]], schema: dict[str, Any]) -> dict | None:
    """One JSON-only completion, or None for the deterministic fallback. Never raises."""
    configured = settings()
    if configured is None:
        return None
    provider, model, key = configured
    try:
        with urllib.request.urlopen(
            _request(provider, model, key, messages, schema), timeout=TIMEOUT_SECONDS
        ) as r:
            reply = json.loads(r.read().decode("utf-8"))
        return _json_object(_text(provider, reply))
    except Exception as exc:  # noqa: BLE001 - any failure means "use the fallback"
        log.warning("LLM call failed (%s); using the deterministic fallback", type(exc).__name__)
        return None
