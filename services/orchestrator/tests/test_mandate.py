"""/flow/mandate/compile against a fake policy-ai (httpx.MockTransport)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app

CALLER = {"X-Orchestrator-Token": "caller-test-token"}
SENTENCE = "never advance more than 70%, never pay more than 12% APR"
ENVELOPE = {"mandate": {"mandate_id": "mdt_001", "max_ltv": "0.70"}, "parser": "deterministic"}
VIOLATIONS = [{"field": "max_ltv", "code": "OUT_OF_RANGE", "value": "0.95", "limit": "0.90"}]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "ORCHESTRATOR_TOKEN", CALLER["X-Orchestrator-Token"])
    return TestClient(app, headers=CALLER)


def policy(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(record)
    monkeypatch.setattr(main, "_client", lambda: httpx.AsyncClient(transport=transport))
    return seen


def test_the_sentence_is_compiled_by_policy_ai_and_its_envelope_returned_unchanged(client, monkeypatch):
    seen = policy(monkeypatch, lambda request: httpx.Response(200, json=ENVELOPE))
    r = client.post("/flow/mandate/compile", json={"text": SENTENCE})
    assert r.status_code == 200 and r.json() == ENVELOPE
    assert [q.url.path for q in seen] == ["/policy/mandate/compile"]
    assert json.loads(seen[0].content) == {"text": SENTENCE}  # only the sentence; nothing is activated


def test_a_refused_sentence_keeps_the_422_and_the_violated_limits(client, monkeypatch):
    policy(monkeypatch, lambda request: httpx.Response(422, json={"detail": VIOLATIONS}))
    r = client.post("/flow/mandate/compile", json={"text": "never advance more than 95%"})
    assert r.status_code == 422 and r.json() == {"detail": VIOLATIONS}


def test_a_failing_or_silent_policy_service_is_a_502(client, monkeypatch):
    policy(monkeypatch, lambda request: httpx.Response(500, text="boom"))
    assert client.post("/flow/mandate/compile", json={"text": SENTENCE}).status_code == 502

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    policy(monkeypatch, down)
    r = client.post("/flow/mandate/compile", json={"text": SENTENCE})
    assert r.status_code == 502 and "unreachable" in r.json()["detail"]


def test_it_needs_the_callers_token(client, monkeypatch):
    seen = policy(monkeypatch, lambda request: httpx.Response(200, json=ENVELOPE))
    anonymous = TestClient(app)
    assert anonymous.post("/flow/mandate/compile", json={"text": SENTENCE}).status_code == 403
    assert seen == []  # policy-ai was never asked


BAD_BODIES = [{}, {"text": ""}, {"text": "x" * 1001}, {"text": SENTENCE, "mandate_id": "x"}]


@pytest.mark.parametrize("body", BAD_BODIES)
def test_a_missing_empty_oversized_or_extra_field_is_refused_before_policy_ai(client, monkeypatch, body):
    seen = policy(monkeypatch, lambda request: httpx.Response(200, json=ENVELOPE))
    assert client.post("/flow/mandate/compile", json=body).status_code == 422
    assert seen == []
