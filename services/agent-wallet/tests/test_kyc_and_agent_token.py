"""The agent token on register, execute and settle, and the mock KYC flag on payees (scope doc section 2)."""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import bootstrap_demo, build_service, create_app
from app.models import Payee, canonical_hash
from app.settings import get_settings
from shared.schemas import PolicyDecision

FP = "0x" + "cd" * 32
AGENT = {"X-Agent-Token": "agent-test-token"}
WRONG = {"X-Agent-Token": "not-the-token"}
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def register_body() -> dict:
    return {
        "idempotency_key": "kyc_1:register",
        "invoice_id": "inv_kyc",
        "invoice_fingerprint": FP,
        "doc_hash": "sha256:kyc",
        "face_value": "749000.00",
        "currency": "THB",
        "due_date": "2026-11-15",
        "seller": "SELLER:siam-fresh-pack",
    }


def draw_body() -> dict:
    d = {
        "decision": "approve",
        "advance_rate": 0.70,
        "limit": "524300.00",
        "fee_rate": 0.009,
        "apr": 0.1095,
        "risk_score": 0.003,
        "reasons": ["Buyer confirmed invoice"],
        "decision_id": "dec_kyc",
        "model_version": "pd-lgbm-0.1.0",
        "policy_version": "policy-0.1.0",
    }
    h = canonical_hash(PolicyDecision.model_validate(d).model_dump(mode="json", exclude={"decision_hash"}))
    return {
        "decision": {**d, "decision_hash": h},
        "payee": "SELLER:siam-fresh-pack",
        "amount": "524300.00",
        "currency": "THB",
        "invoice_id": "inv_kyc",
        "idempotency_key": "kyc_1:draw",
        "decision_id": "dec_kyc",
        "decision_hash": h,
        "invoice_fingerprint": FP,
        "apr": 0.1095,
        "lender_id": "lender_a",
        "mandate_id": "mdt_001",
    }


def settle_body() -> dict:
    return {
        "idempotency_key": "kyc_1:settle",
        "invoice_id": "inv_kyc",
        "invoice_fingerprint": FP,
        "amount_paid": "749000.00",
    }


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("WALLET_OWNER_TOKEN", "owner-test-token")
    monkeypatch.setenv("WALLET_APPROVER_TOKEN", "approver-test-token")
    monkeypatch.setenv("WALLET_RISK_ORACLE_TOKEN", "risk-oracle-test-token")
    monkeypatch.setenv("WALLET_AGENT_TOKEN", "agent-test-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_agent_endpoints_refuse_calls_without_the_agent_token(env):
    service = build_service(clock=Clock(NOW))
    bootstrap_demo(service)
    client = TestClient(create_app(service))  # no default headers
    assert client.post("/wallet/register", json=register_body()).status_code == 403
    assert client.post("/wallet/register", json=register_body(), headers=WRONG).status_code == 403
    assert client.post("/wallet/execute", json=draw_body(), headers=WRONG).status_code == 403
    assert client.post("/wallet/settle", json=settle_body(), headers=WRONG).status_code == 403
    assert client.post("/wallet/register", json=register_body(), headers=AGENT).json()["status"] == "executed"


def test_a_payee_without_kyc_cannot_be_registered(env):
    service = build_service(clock=Clock(NOW))
    seller = service.payees["SELLER:siam-fresh-pack"]
    service.payees["SELLER:siam-fresh-pack"] = seller.model_copy(update={"kyc_verified": False})
    bootstrap_demo(service)
    client = TestClient(create_app(service), headers=AGENT)
    result = client.post("/wallet/register", json=register_body()).json()
    assert result["status"] == "blocked"
    assert result["block_reason"] == "KycNotVerified"


def test_unverified_payees_are_not_allowlisted_on_the_chain(env):
    service = build_service(clock=Clock(NOW))
    seller = service.payees["SELLER:siam-fresh-pack"]
    service.payees["SELLER:siam-fresh-pack"] = seller.model_copy(update={"kyc_verified": False})
    bootstrap_demo(service)
    assert seller.address.lower() not in service.ledger.payees
    assert service.payees["LENDER:lender_a"].address.lower() in service.ledger.payees


def test_a_payee_is_not_verified_unless_flagged():
    assert Payee(name="x", address="0x" + "11" * 20).kyc_verified is False


def test_an_expired_kyc_credential_is_refused_at_registration(env):
    service = build_service(clock=Clock(NOW))  # 12 Oct 2026, Bangkok time
    seller = service.payees["SELLER:siam-fresh-pack"]
    service.payees["SELLER:siam-fresh-pack"] = seller.model_copy(update={"kyc_expiry": date(2026, 10, 11)})
    bootstrap_demo(service)
    client = TestClient(create_app(service), headers=AGENT)
    result = client.post("/wallet/register", json=register_body()).json()
    assert result["status"] == "blocked"
    assert result["block_reason"] == "KycNotVerified"


def test_a_credential_is_verified_through_its_expiry_day(env):
    service = build_service(clock=Clock(NOW))
    seller = service.payees["SELLER:siam-fresh-pack"]
    assert service._seller_kyc(seller.address)  # the demo payees expire on 31 Dec 2026
    service.payees["SELLER:siam-fresh-pack"] = seller.model_copy(update={"kyc_expiry": date(2026, 10, 12)})
    assert service._seller_kyc(seller.address)  # still valid on its last day
    service.payees["SELLER:siam-fresh-pack"] = seller.model_copy(update={"kyc_expiry": date(2026, 10, 11)})
    assert not service._seller_kyc(seller.address)
