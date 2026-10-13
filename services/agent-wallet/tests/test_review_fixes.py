"""Regression tests for the PM review of PR #17."""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import bootstrap_demo, build_service, create_app
from app.models import canonical_hash
from app.settings import get_settings
from shared.schemas import PolicyDecision

SERVICE = Path(__file__).resolve().parents[1]
ORACLE = {"X-Risk-Oracle-Token": "risk-oracle-test-token"}
FP = "0x" + "ab" * 32
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def decision(verdict: str = "approve", limit: str = "524300.00") -> dict:
    return {
        "decision": verdict,
        "advance_rate": 0.70,
        "limit": limit,
        "fee_rate": 0.009,
        "apr": 0.1095,
        "risk_score": 0.003,
        "reasons": ["Buyer confirmed invoice"],
        "decision_id": "dec_1",
        "model_version": "pd-lgbm-0.1.0",
        "policy_version": "policy-0.1.0",
    }


def hash_of(d: dict) -> str:
    return canonical_hash(PolicyDecision.model_validate(d).model_dump(mode="json", exclude={"decision_hash"}))


def register_body() -> dict:
    return {
        "idempotency_key": "fl_1:register",
        "invoice_id": "inv_1",
        "invoice_fingerprint": FP,
        "doc_hash": "sha256:1",
        "face_value": "749000.00",
        "currency": "THB",
        "due_date": "2026-11-15",
        "seller": "SELLER:siam-fresh-pack",
    }


def approve_body(d: dict, **overrides) -> dict:
    body = {
        "idempotency_key": "fl_1:approve",
        "decision_id": "dec_1",
        "decision": d,
        "decision_hash": hash_of(d),
        "invoice_fingerprint": FP,
        "limit": d["limit"],
        "fee_rate": d["fee_rate"],
        "model_version": "pd-lgbm-0.1.0",
        "policy_version": "policy-0.1.0",
    }
    return {**body, **overrides}


def draw_body(amount: str = "524300.00", mandate_id: str = "mdt_001", **overrides) -> dict:
    d = decision()
    h = hash_of(d)
    body = {
        "decision": {**d, "decision_hash": h},
        "payee": "SELLER:siam-fresh-pack",
        "amount": amount,
        "currency": "THB",
        "invoice_id": "inv_1",
        "idempotency_key": "fl_1:draw",
        "decision_id": "dec_1",
        "decision_hash": h,
        "invoice_fingerprint": FP,
        "apr": 0.1095,
        "lender_id": "lender_a",
        "mandate_id": mandate_id,
    }
    return {**body, **overrides}


def without(body: dict, *keys: str) -> dict:
    return {k: v for k, v in body.items() if k not in keys}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("WALLET_OWNER_TOKEN", "owner-test-token")
    monkeypatch.setenv("WALLET_APPROVER_TOKEN", "approver-test-token")
    monkeypatch.setenv("WALLET_RISK_ORACLE_TOKEN", "risk-oracle-test-token")
    monkeypatch.setenv("WALLET_AGENT_TOKEN", "agent-test-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def wallet(env):
    clock = Clock(NOW)
    service = build_service(clock=clock)
    bootstrap_demo(service)
    return TestClient(create_app(service), headers={"X-Agent-Token": "agent-test-token"}), service, clock


def open_receivable(client: TestClient) -> None:
    assert client.post("/wallet/register", json=register_body()).json()["status"] == "executed"


def test_approve_without_the_risk_oracle_token_is_refused(wallet):
    client, _, _ = wallet
    assert client.post("/wallet/approve", json=approve_body(decision())).status_code == 403
    wrong = {"X-Risk-Oracle-Token": "not-the-token"}
    assert client.post("/wallet/approve", json=approve_body(decision()), headers=wrong).status_code == 403


def test_a_review_decision_cannot_be_approved_and_the_draw_stays_blocked(wallet):
    client, _, _ = wallet
    open_receivable(client)
    forged = client.post("/wallet/approve", json=approve_body(decision("review")), headers=ORACLE).json()
    assert forged["status"] == "blocked" and forged["block_reason"] == "NotApproved"
    draw = client.post("/wallet/execute", json=draw_body()).json()
    assert draw["status"] == "blocked" and draw["block_reason"] == "NotApproved"


def test_approval_with_a_tampered_decision_hash_is_blocked(wallet):
    client, _, _ = wallet
    open_receivable(client)
    body = approve_body(decision(), decision_hash="0x" + "11" * 32)
    result = client.post("/wallet/approve", json=body, headers=ORACLE).json()
    assert result["block_reason"] == "DecisionTampered"


def test_approval_limit_must_match_the_decision_it_names(wallet):
    client, _, _ = wallet
    open_receivable(client)
    body = approve_body(decision(), limit="900000.00")  # the hash still matches the decision's own limit
    result = client.post("/wallet/approve", json=body, headers=ORACLE).json()
    assert result["block_reason"] == "DecisionTampered"


def test_approval_without_a_decision_is_refused(wallet):
    client, _, _ = wallet
    open_receivable(client)
    body = without(approve_body(decision()), "decision")
    result = client.post("/wallet/approve", json=body, headers=ORACLE).json()
    assert result["block_reason"] == "SchemaInvalid"


def test_a_draw_without_a_key_or_fingerprint_does_not_replay_another_draw(wallet):
    client, _, _ = wallet
    keyless = ("idempotency_key", "invoice_fingerprint")
    first = client.post("/wallet/execute", json=without(draw_body("524300.00"), *keyless)).json()
    other = client.post("/wallet/execute", json=without(draw_body("100000.00"), *keyless)).json()
    assert other["tx_id"] != first["tx_id"]
    assert "IdempotentReplay" not in [c["code"] for c in other["checks"]]
    same = client.post("/wallet/execute", json=without(draw_body("524300.00"), *keyless)).json()
    assert same["tx_id"] == first["tx_id"]  # an identical retry still replays
    assert "IdempotentReplay" in [c["code"] for c in same["checks"]]


def test_a_draw_naming_another_mandate_is_blocked(wallet):
    client, _, _ = wallet
    open_receivable(client)
    assert client.post("/wallet/approve", json=approve_body(decision()), headers=ORACLE).json()["status"] == (
        "executed"
    )
    result = client.post("/wallet/execute", json=draw_body(mandate_id="mdt_other")).json()
    assert result["block_reason"] == "MandateMismatch"


def test_a_draw_before_the_mandate_starts_is_blocked(env):
    before_start = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)  # the demo mandate is valid from 10 Oct, Bangkok
    service = build_service(clock=Clock(before_start))
    bootstrap_demo(service)
    client = TestClient(create_app(service), headers={"X-Agent-Token": "agent-test-token"})
    open_receivable(client)
    assert client.post("/wallet/approve", json=approve_body(decision()), headers=ORACLE).json()["status"] == (
        "executed"
    )
    result = client.post("/wallet/execute", json=draw_body()).json()
    assert result["block_reason"] == "MandateNotYetValid"


def test_the_app_starts_with_the_demo_mandate_and_liquidity(env):
    service = build_service(clock=Clock(NOW))
    with TestClient(
        create_app(service), headers={"X-Agent-Token": "agent-test-token"}
    ) as client:  # the context manager runs the startup hook
        mandate = client.get("/wallet/mandate").json()
    assert mandate["mandate_id"] == "mdt_001"
    assert service.ledger.balances["vault"] == 1_000_000_000  # two lenders at 5,000,000.00 THB, in satang


def test_the_classifier_module_imports_without_the_onnx_runtime():
    code = (
        "import sys, app.guard.classifier; print('onnxruntime' in sys.modules, 'tokenizers' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=SERVICE, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False False"
