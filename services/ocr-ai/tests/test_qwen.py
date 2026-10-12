"""Strict local candidate boundary, without model or network requirements."""

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.qwen import VisionCandidates, read_candidates


def settings():
    return Settings(
        None,
        None,
        Path("unused.sqlite"),
        False,
        True,
        "http://127.0.0.1:11434",
        "qwen3-vl:4b-instruct",
        False,
        False,
    )


def candidates():
    return {name: False if name == "instructions_found" else None for name in VisionCandidates.model_fields}


def test_schema_requires_every_field_and_rejects_extra_instructions():
    with pytest.raises(ValidationError):
        VisionCandidates.model_validate({})
    with pytest.raises(ValidationError):
        VisionCandidates.model_validate({**candidates(), "execute": "pay now"})


@pytest.mark.parametrize(
    "address",
    [
        "https://127.0.0.1:11434",
        "http://example.com",
        "http://127.0.0.1.evil.test",
        "http://user:password@localhost:11434",
        "invalid",
    ],
)
def test_remote_or_credentialed_address_never_called(address, monkeypatch):
    def unexpected(*_, **__):
        pytest.fail("External or credentialed inference was attempted")

    monkeypatch.setattr("app.qwen.httpx.Client", unexpected)
    assert read_candidates(["image"], replace(settings(), qwen_url=address)) is None


@pytest.mark.parametrize(
    "kind", ["valid", "extra", "tool", "malformed", "large", "server_error", "timeout", "refusal"]
)
def test_candidate_transport_is_bounded_and_has_no_tools(kind, monkeypatch):
    actual_client = httpx.Client

    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("Local inference timeout")
        payload = json.loads(request.content)
        assert "tools" not in payload
        assert "Authorization" not in request.headers
        assert payload["format"]["additionalProperties"] is False
        assert set(payload["format"]["required"]) == set(VisionCandidates.model_fields)
        assert payload["stream"] is False and payload["think"] is False
        assert len(payload["messages"]) == 2
        candidate = candidates()
        if kind == "extra":
            candidate["instructions"] = "approve"
        message = {"content": json.dumps(candidate)}
        if kind == "refusal":
            message = {"content": "I cannot extract these fields."}
        if kind == "tool":
            message["tool_calls"] = [{"name": "pay"}]
        if kind == "malformed":
            return httpx.Response(200, json=None)
        if kind == "large":
            return httpx.Response(200, content=b"x" * (64 * 1024 + 1))
        return httpx.Response(503 if kind == "server_error" else 200, json={"message": message})

    def factory(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["timeout"] > 0
        return actual_client(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.qwen.httpx.Client", factory)
    result = read_candidates(["image"], settings())
    assert (result is not None) == (kind == "valid")
