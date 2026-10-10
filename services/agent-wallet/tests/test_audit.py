"""Audit log: outcomes are recorded, the chain verifies, tampering is caught, and the head is anchored."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import bootstrap_demo, build_service, create_app
from app.models import canonical_hash
from app.settings import get_settings
from shared.schemas import PolicyDecision

FP = "0x" + "11" * 32
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
OWNER = {"X-Owner-Token": "owner-test-token"}


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def decision_dict(limit: str = "524300.00") -> dict:
    return {
        "decision": "approve",
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


def hash_of(decision: dict) -> str:
    return canonical_hash(
        PolicyDecision.model_validate(decision).model_dump(mode="json", exclude={"decision_hash"})
    )


@pytest.fixture
def wallet(monkeypatch):
    monkeypatch.setenv("WALLET_OWNER_TOKEN", "owner-test-token")
    monkeypatch.setenv("WALLET_APPROVER_TOKEN", "approver-test-token")
    monkeypatch.setenv("WALLET_RISK_ORACLE_TOKEN", "risk-oracle-test-token")
    get_settings.cache_clear()
    service = build_service(clock=Clock(NOW))
    bootstrap_demo(service)
    client = TestClient(create_app(service))
    yield client, service
    get_settings.cache_clear()


def open_and_draw(client, amount: str = "524300.00", apr: float = 0.1095, key: str = "fl_1:draw") -> dict:
    client.post(
        "/wallet/register",
        json={
            "idempotency_key": "fl_1:register",
            "invoice_id": "inv_1",
            "invoice_fingerprint": FP,
            "doc_hash": "sha256:1",
            "face_value": "749000.00",
            "currency": "THB",
            "due_date": "2026-11-15",
            "seller": "SELLER:siam-fresh-pack",
        },
    )
    decision = decision_dict(limit=amount)
    client.post(
        "/wallet/approve",
        json={
            "idempotency_key": "fl_1:approve",
            "decision_id": "dec_1",
            "decision": decision,
            "decision_hash": hash_of(decision),
            "invoice_fingerprint": FP,
            "limit": amount,
            "fee_rate": 0.009,
            "model_version": "pd-lgbm-0.1.0",
            "policy_version": "policy-0.1.0",
        },
        headers={"X-Risk-Oracle-Token": "risk-oracle-test-token"},
    )
    body = {
        "decision": {**decision, "decision_hash": hash_of(decision)},
        "payee": "SELLER:siam-fresh-pack",
        "amount": amount,
        "currency": "THB",
        "invoice_id": "inv_1",
        "idempotency_key": key,
        "decision_id": "dec_1",
        "decision_hash": hash_of(decision),
        "invoice_fingerprint": FP,
        "apr": apr,
        "lender_id": "lender_a",
        "mandate_id": "mdt_001",
    }
    return client.post("/wallet/execute", json=body).json()


def test_full_loop_is_audited_anchored_and_verifies(wallet):
    client, service = wallet
    draw = open_and_draw(client)
    assert draw["status"] == "executed"
    client.post(
        "/wallet/settle",
        json={
            "idempotency_key": "fl_1:settle",
            "invoice_id": "inv_1",
            "invoice_fingerprint": FP,
            "amount_paid": "749000.00",
        },
    )
    view = client.get("/wallet/audit/inv_1").json()
    events = [e["event"] for e in view["entries"]]
    assert "EXECUTED" in events
    assert events[-1] == "ANCHORED"
    assert view["verified"] is True
    assert service.ledger.anchors  # the head was written on chain


def test_blocked_attack_leaves_a_blocked_entry_with_the_failing_code(wallet):
    client, _ = wallet
    result = open_and_draw(client, apr=0.19, key="fl_1:draw-apr")
    assert result["block_reason"] == "AprAboveMandate"
    entries = client.get("/wallet/audit/inv_1").json()["entries"]
    blocked = [e for e in entries if e["event"] == "BLOCKED"]
    assert blocked and blocked[-1]["data"]["block_reason"] == "AprAboveMandate"
    failing = [e["data"]["code"] for e in entries if e["event"] == "CHECK" and not e["data"]["passed"]]
    assert "AprAboveMandate" in failing


def test_exact_replay_is_logged_as_a_replay(wallet):
    client, _ = wallet
    first = open_and_draw(client)
    replay = open_and_draw(client)
    assert replay["tx_id"] == first["tx_id"]
    assert "REPLAY" in [e["event"] for e in client.get("/wallet/audit/inv_1").json()["entries"]]


def test_editing_an_entry_fails_verification(wallet):
    client, service = wallet
    open_and_draw(client)
    service.audit.entries[-1]["data"]["block_reason"] = "forged"
    assert client.get("/wallet/audit/inv_1").json()["verified"] is False


def test_dropping_an_entry_breaks_the_chain(wallet):
    client, service = wallet
    open_and_draw(client)
    del service.audit.entries[1]
    assert client.get("/wallet/audit/inv_1").json()["verified"] is False


def test_audit_by_ref_returns_the_entries_for_one_action(wallet):
    client, _ = wallet
    result = open_and_draw(client)
    by_ref = client.get(f"/wallet/audit/ref/{result['audit_ref']}").json()
    assert by_ref["entries"]
    assert {e["audit_ref"] for e in by_ref["entries"]} == {result["audit_ref"]}
    assert by_ref["verified"] is True


def test_tx_lookup_returns_the_result_and_404s_unknown_ids(wallet):
    client, _ = wallet
    result = open_and_draw(client)
    assert client.get(f"/wallet/tx/{result['tx_id']}").json()["tx_id"] == result["tx_id"]
    assert client.get("/wallet/tx/tx_unknown").status_code == 404


def test_audit_entries_carry_no_invoice_text(wallet):
    client, _ = wallet
    open_and_draw(client)
    serialised = str(client.get("/wallet/audit/inv_1").json())
    assert "Buyer confirmed invoice" not in serialised
