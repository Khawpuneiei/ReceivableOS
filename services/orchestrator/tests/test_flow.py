"""/flow/run and /flow/repay against fake ocr-ai, policy-ai and agent-wallet services (httpx.MockTransport).

Each test checks what the orchestrator sends: the call order, the token header each wallet route needs, and
the fields the wallet's guard binds to (fingerprint, doc_hash, decision_hash, payee id, lender, mandate).
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app

FP = "0x" + "11" * 32
DECISION_HASH = "0x" + "22" * 32
AGENT = "agent-test-token"
RISK_ORACLE = "risk-oracle-test-token"

INVOICE = {
    "invoice_id": "obs_1",
    "supplier": {"name": "Siam Fresh Pack Co., Ltd.", "tax_id": "0105559000000"},
    "buyer": {"name": "Mekong Basket Retail PCL", "tax_id": "0107559000001"},
    "invoice_no": "SFP-INV-2026-0142",
    "issue_date": "2026-10-01",
    "due_date": "2026-11-15",
    "amount": "749000.00",
    "currency": "THB",
    "line_items": [],
    "confidence": 0.97,
    "injection_flags": [],
    "fraud_score": 0.0,
    "fraud_flags": [],
    "doc_hash": "sha256:" + "ab" * 32,
    "invoice_fingerprint": FP,
}


def decision(kind: str = "approve") -> dict:
    return {
        "decision": kind,
        "advance_rate": "0.70",
        "limit": "524300.00",
        "fee_rate": "0.009",
        "apr": "0.1095",
        "risk_score": 0.003,
        "reasons": ["TERMS.MANDATE_CAP: Advance capped by the mandate"],
        "model_version": "credit-lr-test",
        "policy_version": "credit-policy-test",
        "decision_id": "dec_1",
        "decision_hash": DECISION_HASH,
    }


def wallet_result(status: str = "executed", block_reason: str | None = None) -> dict:
    return {
        "tx_id": "tx_1",
        "status": status,
        "chain_ref": "mock:0x" + "cd" * 32,
        "approvals_required": 0,
        "audit_ref": "aud_1",
        "chain": "mock",
        "block_reason": block_reason,
        "checks": [],
    }


class Services:
    """Fake downstream services. Records every call as (path, headers, body)."""

    def __init__(self, decision_kind: str = "approve", register: dict | None = None) -> None:
        self.calls: list[tuple[str, httpx.Headers, dict | None]] = []
        self.decision_kind = decision_kind
        self.register = register or wallet_result()

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = (
            json.loads(request.content)
            if request.headers.get("content-type", "") == "application/json"
            else None
        )
        self.calls.append((path, request.headers, body))
        if path == "/ocr/extract":
            return httpx.Response(200, json=INVOICE)
        if path == "/policy/decide":
            return httpx.Response(200, json=decision(self.decision_kind))
        if path == "/wallet/register":
            return httpx.Response(200, json=self.register)
        if path in ("/wallet/approve", "/wallet/execute", "/wallet/settle"):
            return httpx.Response(200, json=wallet_result())
        return httpx.Response(404, json={"detail": f"no fake for {path}"})

    def paths(self) -> list[str]:
        return [p for p, _, _ in self.calls]

    def call(self, path: str) -> tuple[httpx.Headers, dict]:
        _, headers, body = next(c for c in self.calls if c[0] == path)
        return headers, body


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "WALLET_AGENT_TOKEN", AGENT)
    monkeypatch.setattr(main, "WALLET_RISK_ORACLE_TOKEN", RISK_ORACLE)
    main._flows.clear()
    return TestClient(app)


def wire(monkeypatch, services: Services) -> None:
    transport = httpx.MockTransport(services.handler)
    monkeypatch.setattr(main, "_client", lambda: httpx.AsyncClient(transport=transport))


def run(client: TestClient, **data) -> dict:
    r = client.post(
        "/flow/run", files={"file": ("01_happy.pdf", b"%PDF-1.4 test", "application/pdf")}, data=data
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_approve_runs_register_approve_execute_in_order(client, monkeypatch):
    services = Services()
    wire(monkeypatch, services)
    steps = run(client)
    assert services.paths() == [
        "/ocr/extract",
        "/wallet/register",
        "/policy/decide",
        "/wallet/approve",
        "/wallet/execute",
    ]
    assert steps["outcome"] == "executed"
    assert steps["registry"] == {"invoice_fingerprint": FP, "duplicate": False}
    assert steps["wallet"]["status"] == "executed"
    assert steps["mandate_id"] == "mdt_001"  # the demo mandate the wallet activates; what the UI sends too


def test_register_carries_the_agent_token_and_the_ocr_hashes(client, monkeypatch):
    services = Services()
    wire(monkeypatch, services)
    run(client)
    headers, body = services.call("/wallet/register")
    assert headers["X-Agent-Token"] == AGENT
    assert body == {
        "idempotency_key": "obs_1:register",
        "invoice_id": "obs_1",
        "invoice_fingerprint": FP,
        "doc_hash": INVOICE["doc_hash"],
        "face_value": "749000.00",
        "currency": "THB",
        "due_date": "2026-11-15",
        "seller": "SELLER:siam-fresh-pack",
    }


def test_approve_carries_the_risk_oracle_token_and_the_whole_decision(client, monkeypatch):
    services = Services()
    wire(monkeypatch, services)
    run(client)
    headers, body = services.call("/wallet/approve")
    assert headers["X-Risk-Oracle-Token"] == RISK_ORACLE
    assert "X-Agent-Token" not in headers  # the agent must not be able to approve its own credit
    assert body["decision"] == decision()  # the wallet recomputes decision_hash from it
    assert (body["decision_id"], body["decision_hash"]) == ("dec_1", DECISION_HASH)
    assert (body["limit"], body["fee_rate"]) == ("524300.00", "0.009")
    assert body["invoice_fingerprint"] == FP
    assert body["idempotency_key"] == "obs_1:approve"


def test_execute_binds_payee_id_fingerprint_decision_hash_lender_and_mandate(client, monkeypatch):
    services = Services()
    wire(monkeypatch, services)
    steps = run(client)
    headers, body = services.call("/wallet/execute")
    assert headers["X-Agent-Token"] == AGENT
    assert body["payee"] == "SELLER:siam-fresh-pack"  # a registry id, never an address from the invoice
    assert body["amount"] == "524300.00"  # 70% of 749,000.00, equal to the approved limit
    assert body["currency"] == "THB"
    assert body["decision"]["decision_hash"] == DECISION_HASH
    assert (body["decision_id"], body["decision_hash"]) == ("dec_1", DECISION_HASH)
    assert (body["invoice_id"], body["invoice_fingerprint"], body["doc_hash"]) == (
        "obs_1",
        FP,
        INVOICE["doc_hash"],
    )
    assert (body["lender_id"], body["apr"], body["mandate_id"]) == ("lender_a", "0.1095", "mdt_001")
    assert body["idempotency_key"] == "obs_1:draw"
    chosen = [o for o in steps["offers"] if o["chosen"]]
    assert [o["lender_id"] for o in chosen] == ["lender_a"]
    assert all(o["within_mandate"] for o in steps["offers"])


def test_mandate_id_from_the_form_is_forwarded_to_the_draw(client, monkeypatch):
    services = Services()
    wire(monkeypatch, services)
    steps = run(client, mandate_id="mdt_other")
    assert steps["mandate_id"] == "mdt_other"
    assert services.call("/wallet/execute")[1]["mandate_id"] == "mdt_other"


@pytest.mark.parametrize("kind", ["review", "reject"])
def test_non_approve_decision_never_reaches_approve_or_execute(client, monkeypatch, kind):
    services = Services(decision_kind=kind)
    wire(monkeypatch, services)
    steps = run(client)
    assert services.paths() == ["/ocr/extract", "/wallet/register", "/policy/decide"]
    assert steps["policy"]["decision"] == kind
    assert "wallet" not in steps and "approve" not in steps
    assert steps["outcome"] == f"{kind}: wallet not called"


def test_duplicate_receivable_stops_before_policy(client, monkeypatch):
    services = Services(register=wallet_result("blocked", "DuplicateReceivable"))
    wire(monkeypatch, services)
    steps = run(client)
    assert services.paths() == ["/ocr/extract", "/wallet/register"]
    assert steps["registry"]["duplicate"] is True
    assert steps["outcome"] == "blocked: DuplicateReceivable"
    assert "policy" not in steps


def test_repay_settles_through_the_wallet_with_the_remembered_hashes(client, monkeypatch):
    services = Services()
    wire(monkeypatch, services)
    run(client)
    r = client.post("/flow/repay", data={"invoice_id": "obs_1"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "executed"
    assert r.json()["invoice_id"] == "obs_1"
    headers, body = services.call("/wallet/settle")
    assert headers["X-Agent-Token"] == AGENT
    assert body == {
        "idempotency_key": "obs_1:settle",
        "invoice_id": "obs_1",
        "invoice_fingerprint": FP,
        "doc_hash": INVOICE["doc_hash"],
        "amount_paid": "749000.00",  # the face value unless the form says otherwise
        "paid_at": None,
    }


def test_repay_accepts_a_partial_payment_and_a_date(client, monkeypatch):
    services = Services()
    wire(monkeypatch, services)
    run(client)
    client.post("/flow/repay", data={"invoice_id": "obs_1", "amount_paid": "709000", "paid_at": "2026-11-30"})
    _, body = services.call("/wallet/settle")
    assert (body["amount_paid"], body["paid_at"]) == ("709000.00", "2026-11-30")


def test_repay_of_an_unknown_invoice_is_404(client, monkeypatch):
    services = Services()
    wire(monkeypatch, services)
    r = client.post("/flow/repay", data={"invoice_id": "obs_unknown"})
    assert r.status_code == 404
    assert services.paths() == []


def test_a_wallet_refusal_is_reported_as_502_with_its_reason(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ocr/extract":
            return httpx.Response(200, json=INVOICE)
        return httpx.Response(403, json={"detail": "Unauthorized"})

    monkeypatch.setattr(main, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    r = client.post("/flow/run", files={"file": ("01_happy.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert r.status_code == 502
    assert "/wallet/register answered 403" in r.json()["detail"]
    assert "Unauthorized" in r.json()["detail"]


def test_an_upload_ocr_refuses_keeps_its_4xx_and_reaches_nothing_else(client, monkeypatch):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(415, json={"detail": "Only signature-verified PDF, JPEG, and PNG uploads"})

    monkeypatch.setattr(main, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    r = client.post("/flow/run", files={"file": ("notes.txt", b"not an invoice", "text/plain")})
    assert r.status_code == 415  # the caller's file is at fault, not a service: no 502
    assert "/ocr/extract answered 415" in r.json()["detail"]
    assert seen == ["/ocr/extract"]


def test_an_ocr_outage_is_still_a_502(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "FINGERPRINT_HMAC_KEY is not configured"})

    monkeypatch.setattr(main, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    r = client.post("/flow/run", files={"file": ("01_happy.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert r.status_code == 502
    assert "/ocr/extract answered 503" in r.json()["detail"]


def test_select_quote_prefers_the_highest_advance_within_the_approved_apr():
    chosen, offers = main.select_quote(decision())
    assert chosen["lender_id"] == "lender_a"  # 70% at 10.95% beats 65% at 9.13%
    assert [o["within_mandate"] for o in offers] == [True, True]

    cheaper = {**decision(), "apr": "0.0913", "fee_rate": "0.0075"}
    chosen, offers = main.select_quote(cheaper)
    assert chosen["lender_id"] == "lender_b"  # lender_a's 10.95% is above the approved 9.13%
    assert [o["within_mandate"] for o in offers] == [False, True]

    none, _ = main.select_quote({**decision(), "apr": None, "fee_rate": "0.001"})
    assert none is None  # falls back to shared.money.fee_rate_30d_to_apr; 1.22% APR fits no quote
