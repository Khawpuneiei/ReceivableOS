"""The orchestrator's flow and wallet steps: register, approve, execute, settle, the caller check and resume.
The other services are stubbed here."""

import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main

SELLER = "SELLER:siam-fresh-pack"
CALLER = {"X-Orchestrator-Token": "caller-test-token"}
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
PDF = ("01_happy.pdf", b"%PDF-1.4 stub")


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


class OcrRefuses(Upstream):
    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ocr/extract":
            self.calls.append((request.url.path, dict(request.headers), None))
            return httpx.Response(415, json={"detail": "Only PDF, JPEG and PNG uploads are supported"})
        return super().__call__(request)


class PolicyRefuses(Upstream):
    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/policy/decide":
            self.calls.append((request.url.path, dict(request.headers), None))
            return httpx.Response(422, json={"detail": "invalid request"})
        return super().__call__(request)


class WalletUnreachable(Upstream):
    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/wallet/"):
            self.calls.append((request.url.path, dict(request.headers), None))
            raise httpx.ConnectError("connection refused", request=request)
        return super().__call__(request)


def serve(monkeypatch, upstream: Upstream) -> None:
    """Route every httpx call to the stub and reset the orchestrator's state and tokens."""
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(upstream), **kw)
    )
    monkeypatch.setattr(main, "ORCHESTRATOR_TOKEN", "caller-test-token")
    monkeypatch.setattr(main, "WALLET_AGENT_TOKEN", "agent-test-token")
    monkeypatch.setattr(main, "WALLET_RISK_ORACLE_TOKEN", "oracle-test-token")
    monkeypatch.setattr(main, "_flows", {})


@pytest.fixture
def world(monkeypatch):
    upstream = Upstream()
    serve(monkeypatch, upstream)
    return upstream


def run_flow(headers: dict = CALLER) -> dict:
    r = TestClient(main.app).post("/flow/run", headers=headers, files={"file": PDF})
    assert r.status_code == 200, r.text
    return r.json()


def repay(data: dict, headers: dict = CALLER):
    return TestClient(main.app).post("/flow/repay", headers=headers, data=data)


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


def test_callers_without_the_token_are_refused_before_anything_runs(world, monkeypatch):
    client = TestClient(main.app)
    assert client.post("/flow/run", files={"file": PDF}).status_code == 403
    assert (
        client.post("/flow/run", files={"file": PDF}, headers={"X-Orchestrator-Token": "wrong"}).status_code
        == 403
    )
    assert client.post("/flow/repay", data={"invoice_id": "inv_test_1"}).status_code == 403
    assert world.calls == []  # nothing reached ocr-ai, policy-ai or the wallet

    monkeypatch.setattr(main, "ORCHESTRATOR_TOKEN", "")  # no token configured: every caller is refused
    assert (
        client.post("/flow/run", files={"file": PDF}, headers={"X-Orchestrator-Token": ""}).status_code == 403
    )
    assert world.calls == []


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


def test_a_failed_approve_resumes_on_the_retry(world):
    world.replies["/wallet/approve"] = (503, {"detail": "unavailable"})
    first = run_flow()
    assert first["outcome"].startswith("failed: wallet returned HTTP 503")

    world.replies.pop("/wallet/approve")
    world.calls.clear()
    second = run_flow()

    assert second["outcome"] == "executed"
    # The retry does not register again or re-run the policy. It approves and draws with the stored decision.
    assert world.paths() == ["/ocr/extract", "/wallet/approve", "/wallet/execute"]


def test_a_second_run_of_a_financed_invoice_is_refused(world):
    run_flow()
    world.calls.clear()
    result = run_flow()

    assert result["outcome"] == "blocked: invoice already financed"
    assert not [p for p in world.paths() if p.startswith("/wallet/")]


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
    result = run_flow()

    assert result["outcome"] == "pending_approval"
    assert repay({"invoice_id": "inv_test_1"}).json()["outcome"].startswith("not settled")


def test_repay_settles_the_financed_invoice(world):
    run_flow()
    result = repay({"invoice_id": "inv_test_1"}).json()

    assert result["outcome"] == "executed"
    headers, body = world.call("/wallet/settle")
    assert headers["x-agent-token"] == "agent-test-token"
    assert body["amount_paid"] == "749000.00"
    assert body["invoice_fingerprint"] == INVOICE["invoice_fingerprint"]


@pytest.mark.parametrize("raw", ["0", "-5", "749000.01", "abc", "10.555", "NaN"])
def test_a_repayment_amount_must_be_a_sensible_money_amount(world, raw):
    run_flow()
    assert repay({"invoice_id": "inv_test_1", "amount_paid": raw}).status_code == 422


def test_a_short_payment_is_allowed_and_passed_to_the_wallet(world):
    run_flow()
    result = repay({"invoice_id": "inv_test_1", "amount_paid": "1.00"}).json()

    assert (
        result["outcome"] == "executed"
    )  # the wallet's waterfall and flags decide what a short payment means
    _, body = world.call("/wallet/settle")
    assert body["amount_paid"] == "1.00"


@pytest.mark.parametrize(
    "path,status,expected",
    [
        ("/ocr/extract", None, "failed: ocr-ai returned HTTP 415"),
        ("/policy/decide", None, "failed: policy-ai returned HTTP 422"),
    ],
)
def test_an_upstream_refusal_is_a_result_not_a_500(monkeypatch, path, status, expected):
    upstream = OcrRefuses() if path == "/ocr/extract" else PolicyRefuses()
    serve(monkeypatch, upstream)
    r = TestClient(main.app).post("/flow/run", headers=CALLER, files={"file": PDF})

    assert r.status_code == 200
    assert r.json()["outcome"].startswith(expected)


def test_an_unreachable_wallet_is_a_result_not_a_500(monkeypatch):
    serve(monkeypatch, WalletUnreachable())
    r = TestClient(main.app).post("/flow/run", headers=CALLER, files={"file": PDF})

    assert r.status_code == 200
    assert r.json()["outcome"] == "failed: wallet returned HTTP 503: wallet unreachable"


def test_the_quote_is_the_best_advance_inside_the_apr_cap(monkeypatch):
    face, limit = Decimal("749000.00"), Decimal("524300.00")
    assert main.select_quote(face, limit)["lender_id"] == "lender_a"  # 10.95% is inside 12%
    monkeypatch.setattr(main, "MAX_APR", Decimal("0.10"))
    quote = main.select_quote(face, limit)
    assert quote["lender_id"] == "lender_b" and quote["amount"] == Decimal("486850.00")  # 65% of face
    monkeypatch.setattr(main, "MAX_APR", Decimal("0.05"))
    assert main.select_quote(face, limit) is None


def test_the_draw_never_exceeds_the_approved_limit():
    # A limit below the quoted advance wins: the wallet would refuse anything above it.
    quote = main.select_quote(Decimal("749000.00"), Decimal("400000.00"))
    assert quote["amount"] == Decimal("400000.00")
