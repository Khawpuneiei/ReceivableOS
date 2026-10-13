"""The orchestrator's wallet steps: register, approve, execute, settle.
The other services are stubbed here."""

import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main

SELLER = "SELLER:siam-fresh-pack"
INVOICE = {
    "invoice_id": "inv_test_1",
    "amount": "749000.00",
    "currency": "THB",
    "due_date": "2026-11-15",
    "doc_hash": "sha256:" + "ab" * 32,
    "invoice_fingerprint": "0x" + "cd" * 32,
}
DECISION = {
    "decision": "approve",
    "advance_rate": "0.70",
    "limit": "524300.00",
    "fee_rate": "0.009",
    "apr": "0.1095",
    "risk_score": "0.003",
    "reasons": [],
    "model_version": "pd-lgbm-0.1.0",
    "policy_version": "policy-0.1.0",
    "decision_id": "dec_test_1",
    "decision_hash": "0x" + "ef" * 32,
}
EXECUTED = {"status": "executed", "tx_id": "tx_1", "audit_ref": "aud_1"}


class Upstream:
    """Stands in for ocr-ai, policy-ai and agent-wallet. Records every request it receives."""

    def __init__(self) -> None:
        self.decision = DECISION
        self.replies: dict[str, tuple[int, dict]] = {}  # wallet path -> (HTTP status, body)
        self.calls: list[tuple[str, dict, dict | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        is_json = request.headers.get("content-type", "").startswith("application/json")
        self.calls.append((path, dict(request.headers), json.loads(request.content) if is_json else None))
        if path == "/ocr/extract":
            return httpx.Response(200, json=INVOICE)
        if path == "/policy/decide":
            return httpx.Response(200, json=self.decision)
        status, body = self.replies.get(path, (200, EXECUTED))
        return httpx.Response(status, json=body)

    def paths(self) -> list[str]:
        return [path for path, _, _ in self.calls]

    def call(self, path: str) -> tuple[dict, dict | None]:
        """Headers and body of the first call to this path."""
        for p, headers, body in self.calls:
            if p == path:
                return headers, body
        raise AssertionError(f"no call to {path}: {self.paths()}")


@pytest.fixture
def world(monkeypatch):
    upstream = Upstream()
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(upstream), **kw)
    )
    monkeypatch.setattr(main, "WALLET_AGENT_TOKEN", "agent-test-token")
    monkeypatch.setattr(main, "WALLET_RISK_ORACLE_TOKEN", "oracle-test-token")
    monkeypatch.setattr(main, "_registered", set())
    monkeypatch.setattr(main, "_financed", {})
    return upstream


def run_flow() -> dict:
    r = TestClient(main.app).post("/flow/run", files={"file": ("01_happy.pdf", b"%PDF-1.4 stub")})
    assert r.status_code == 200, r.text
    return r.json()


def test_an_approved_invoice_is_registered_approved_and_drawn(world):
    result = run_flow()

    assert result["outcome"] == "executed"
    assert world.paths() == [
        "/ocr/extract",
        "/policy/decide",
        "/wallet/register",
        "/wallet/approve",
        "/wallet/execute",
    ]

    headers, body = world.call("/wallet/register")
    assert headers["x-agent-token"] == "agent-test-token"
    assert body["seller"] == SELLER and body["face_value"] == "749000.00"

    headers, body = world.call("/wallet/approve")
    assert headers["x-risk-oracle-token"] == "oracle-test-token"
    assert body["limit"] == "524300.00" and body["decision_hash"] == DECISION["decision_hash"]

    headers, body = world.call("/wallet/execute")
    assert headers["x-agent-token"] == "agent-test-token"
    assert body["payee"] == SELLER
    assert body["amount"] == "524300.00"  # 70% of 749,000.00, which is the approved limit
    assert body["apr"] == "0.1095" and body["lender_id"] == "lender_a"
    assert body["mandate_id"] == "mdt_001"
    assert body["decision_hash"] == DECISION["decision_hash"]


def test_a_wallet_refusal_is_reported_not_raised(world):
    world.replies["/wallet/register"] = (403, {"detail": "Unauthorized"})
    result = run_flow()

    assert result["outcome"].startswith("failed: wallet returned HTTP 403")
    assert "/wallet/approve" not in world.paths()
    assert "/wallet/execute" not in world.paths()


def test_a_blocked_register_stops_before_approval(world):
    world.replies["/wallet/register"] = (200, {"status": "blocked", "block_reason": "KycNotVerified"})
    result = run_flow()

    assert result["outcome"] == "blocked: KycNotVerified"
    assert "/wallet/approve" not in world.paths()


def test_a_declined_policy_moves_nothing(world):
    world.decision = {**DECISION, "decision": "reject"}
    result = run_flow()

    assert result["outcome"] == "not financed: policy decision is reject"
    assert not [p for p in world.paths() if p.startswith("/wallet/")]


def test_a_draw_waiting_for_an_approver_is_not_settled_yet(world):
    world.replies["/wallet/execute"] = (
        200,
        {"status": "pending_approval", "tx_id": "tx_2", "audit_ref": "aud_2"},
    )
    client = TestClient(main.app)
    result = run_flow()

    assert result["outcome"] == "pending_approval"
    repay = client.post("/flow/repay", data={"invoice_id": "inv_test_1"}).json()
    assert repay["outcome"].startswith("not settled")


def test_repay_settles_the_financed_invoice(world):
    run_flow()
    repay = TestClient(main.app).post("/flow/repay", data={"invoice_id": "inv_test_1"}).json()

    assert repay["outcome"] == "executed"
    headers, body = world.call("/wallet/settle")
    assert headers["x-agent-token"] == "agent-test-token"
    assert body["amount_paid"] == "749000.00"
    assert body["invoice_fingerprint"] == INVOICE["invoice_fingerprint"]


def test_the_quote_is_the_best_advance_inside_the_apr_cap(monkeypatch):
    face, limit = Decimal("749000.00"), Decimal("524300.00")
    assert main.select_quote(face, limit)["lender_id"] == "lender_a"  # 10.95% is inside 12%
    monkeypatch.setattr(main, "MAX_APR", Decimal("0.10"))
    quote = main.select_quote(face, limit)
    assert quote["lender_id"] == "lender_b" and quote["amount"] == Decimal("486850.00")  # 65% of face
    monkeypatch.setattr(main, "MAX_APR", Decimal("0.05"))
    assert main.select_quote(face, limit) is None


def test_the_draw_never_exceeds_the_approved_limit(monkeypatch):
    # A limit below the quoted advance wins: the wallet would refuse anything above it.
    quote = main.select_quote(Decimal("749000.00"), Decimal("400000.00"))
    assert quote["amount"] == Decimal("400000.00")
