"""Checklist regressions over real bytes, keyed transport and protected result retrieval."""

import hashlib
import json

import httpx
import pytest
from datagen.security_corpus import MECHANISMS, overlay
from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf

from app.cache import JsonCache
from app.ingest import digest
from app.llm_client import read_hosted_candidates
from app.qwen import VisionCandidates
from app.worker import parse


@pytest.mark.parametrize("mechanism", MECHANISMS)
def test_real_pdf_attack_cannot_change_contract_fields(client, mechanism):
    content = overlay(build_pdf(SHOWCASE_PROFILES[0]), mechanism)
    response = client.post("/ocr/extract", files={"file": ("invoice.pdf", content, "application/pdf")})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["injection_flags"] and result["review_required"]
    for key, expected in {
        "amount": "749000.00",
        "invoice_no": "SFP-INV-2026-0142",
        "issue_date": "2026-10-01",
        "due_date": "2026-11-15",
        "currency": "THB",
    }.items():
        assert result[key] == expected
    assert result["supplier"]["name"] == SHOWCASE_PROFILES[0]["supplier"]
    assert result["buyer"]["name"] == SHOWCASE_PROFILES[0]["buyer"]
    assert result["doc_hash"] == "sha256:" + hashlib.sha256(content).hexdigest()


def test_qr_is_private_and_links_are_not_followed(client):
    content = overlay(build_pdf(SHOWCASE_PROFILES[0]), "qr", benign=True)
    assert parse(content).qr_payloads == ["https://invoice.example/verify/fictional"]
    response = client.post("/ocr/extract", files={"file": ("invoice.pdf", content, "application/pdf")})
    assert response.status_code == 200
    assert not response.json()["injection_flags"]
    assert "invoice.example" not in response.text


def test_invoice_get_requires_token_and_preserves_response(client, monkeypatch):
    monkeypatch.setenv("OCR_RESULT_ACCESS_TOKEN", "private-test-token")
    response = client.post(
        "/ocr/extract", files={"file": ("i.pdf", build_pdf(SHOWCASE_PROFILES[0]), "application/pdf")}
    )
    url = "/ocr/invoices/" + response.json()["invoice_id"]
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"X-OCR-Result-Token": "wrong"}).status_code == 401
    assert client.get(url, headers={"X-OCR-Result-Token": "private-test-token"}).json() == response.json()
    monkeypatch.setenv("OCR_STATE_PATH", "other-context")
    assert client.get(url, headers={"X-OCR-Result-Token": "private-test-token"}).status_code == 404


def test_expiration_eviction_and_defensive_copy(monkeypatch):
    clock = [1]
    monkeypatch.setattr("app.cache.time.monotonic", lambda: clock[0])
    cache = JsonCache(capacity=1, ttl=5, max_bytes=100)
    cache.put("first", {"values": [1]})
    cache.get("first")["values"].append(2)
    assert cache.get("first") == {"values": [1]}
    cache.put("second", {"values": [2]})
    assert cache.get("first") is None
    clock[0] += 6
    assert cache.get("second") is None
    cache.put("oversized", {"text": "x" * 200})
    assert cache.get("oversized") is None


@pytest.mark.parametrize("kind", ["valid", "tool", "extra", "invalid", "timeout", "large", "refusal"])
def test_hosted_transport_cache_validation_and_key_isolation(monkeypatch, kind):
    monkeypatch.setenv("LLM_API_KEY", "fake-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "configured-test-model")
    actual_client, calls = httpx.Client, []

    def handler(request):
        calls.append(request)
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        payload = json.loads(request.content)
        assert "tools" not in payload
        assert "fake-test-key" not in json.dumps(payload)
        if kind == "timeout":
            raise httpx.ReadTimeout("test")
        if kind == "large":
            return httpx.Response(200, content=b"x" * 65537)
        value = {
            name: False if name == "instructions_found" else None for name in VisionCandidates.model_fields
        }
        if kind == "extra":
            value["execute"] = "pay"
        content = [{"type": "text", "text": json.dumps(value) if kind != "invalid" else "not json"}]
        if kind == "tool":
            content = [{"type": "tool_use", "name": "pay"}]
        return httpx.Response(
            200, json={"content": content, "stop_reason": "refusal" if kind == "refusal" else "end_turn"}
        )

    monkeypatch.setattr(
        "app.llm_client.httpx.Client",
        lambda **kw: actual_client(**kw, transport=httpx.MockTransport(handler)),
    )
    first, status = read_hosted_candidates(["image"])
    second, next_status = read_hosted_candidates(["image"])
    assert (first is not None) == (kind == "valid")
    assert (second is not None) == (kind == "valid")
    assert len(calls) == (1 if kind == "valid" else 2)
    if kind == "valid":
        assert (status, next_status) == ("miss", "hit")
        monkeypatch.setenv("LLM_API_KEY", "another-fake-key")
        assert read_hosted_candidates(["image"])[1] == "miss"
        assert len(calls) == 2


def test_image_raw_digest_is_not_rendered_digest():
    import base64
    from io import BytesIO

    from PIL import Image

    for fmt in ("PNG", "JPEG"):
        stream = BytesIO()
        Image.new("RGB", (32, 32), "white").save(stream, format=fmt)
        raw = stream.getvalue()
        parsed = parse(raw)
        assert parsed.doc_hash == digest(raw)
        assert base64.b64decode(parsed.images[0]).startswith(b"\x89PNG")


def test_hosted_candidate_disagreement_keeps_grounded_amount_and_prewarm_skips_observation(
    client, monkeypatch, tmp_path
):
    monkeypatch.setenv("OCR_RESULT_ACCESS_TOKEN", "test-operator-token")
    monkeypatch.setenv("LLM_API_KEY", "fake-test-key")
    monkeypatch.setenv("LLM_MODEL", "configured-test-model")
    actual_client, calls = httpx.Client, []

    def handler(request):
        calls.append(request)
        value = {
            name: False if name == "instructions_found" else None for name in VisionCandidates.model_fields
        }
        value["amount"] = "0.01"
        return httpx.Response(
            200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(value)}]}
        )

    monkeypatch.setattr(
        "app.llm_client.httpx.Client",
        lambda **kw: actual_client(**kw, transport=httpx.MockTransport(handler)),
    )
    content = build_pdf(SHOWCASE_PROFILES[0])
    upload = {"file": ("i.pdf", content, "application/pdf")}
    assert client.post("/ocr/llm/prewarm", files=upload).status_code == 401
    warm = client.post(
        "/ocr/llm/prewarm", files=upload, headers={"X-OCR-Result-Token": "test-operator-token"}
    )
    assert warm.status_code == 200 and not warm.json()["observation_written"]
    assert not (tmp_path / "state.sqlite").exists()
    response = client.post("/ocr/extract", files=upload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["amount"] == "749000.00"
    assert body["review_required"] and "HOSTED_LLM_DISAGREEMENT:amount" in body["validation_flags"]
    assert not body["fraud_flags"]
    assert body["model_checks"] == [{"provider": "hosted", "cache": "hit"}]
    assert len(calls) == 1


def test_generated_demo_order_is_approve_review_reject_duplicate_by_evidence(client, tmp_path):
    from datagen.showcase_invoices import generate

    generate(tmp_path / "showcase")
    results = []
    for file in sorted((tmp_path / "demo").glob("0[1-4]_*.pdf")):
        response = client.post(
            "/ocr/extract", files={"file": (file.name, file.read_bytes(), "application/pdf")}
        )
        assert response.status_code == 200, response.text
        results.append(response.json())
    happy, injected, inflated, duplicate = results
    assert happy["fraud_score"] < 0.30 and not happy["review_required"]
    assert injected["fraud_score"] < 0.30 and injected["injection_flags"] and injected["review_required"]
    assert "duplicate_fingerprint" not in injected["fraud_flags"]
    assert inflated["fraud_score"] >= 0.30 and "math_inconsistent" in inflated["fraud_flags"]
    assert duplicate["fraud_score"] >= 0.30
    assert {"duplicate_invoice_hash", "duplicate_fingerprint"} <= set(duplicate["fraud_flags"])
    assert happy["doc_hash"] == duplicate["doc_hash"]
    assert happy["invoice_fingerprint"] == duplicate["invoice_fingerprint"]
