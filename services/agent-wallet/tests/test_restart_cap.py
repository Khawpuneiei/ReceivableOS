"""A restarted wallet counts what the chain already spent in the last 24h (FISCO: PolicyGuard.rollingSpend).

The store is in memory. Without the startup read, the off-chain daily cap would start from zero after every
restart, and only the chain would stop the draw.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import bootstrap_demo, build_service, create_app
from app.models import canonical_hash, load_mandate, load_payees
from app.settings import get_settings
from app.wallet.lifecycle import WalletService
from app.wallet.store import Store
from shared.schemas import PolicyDecision

CONFIG = Path(__file__).resolve().parents[1] / "config"
FP = "0x" + "22" * 32
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
AGENT = {"X-Agent-Token": "agent-test-token"}
RISK_ORACLE = {"X-Risk-Oracle-Token": "risk-oracle-test-token"}


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class ChainStub:
    """The two reads the FISCO branch of bootstrap_demo makes. `spent` is returned, or raised."""

    name = "fisco"

    def __init__(self, spent: Decimal | Exception) -> None:
        self.spent = spent

    def mandate_hash_onchain(self) -> str:
        return load_mandate(CONFIG / "mandate.demo.json").mandate_hash

    def rolling_spend(self) -> Decimal:
        if isinstance(self.spent, Exception):
            raise self.spent
        return self.spent


def decision(limit: str = "524300.00") -> dict:
    return {
        "decision": "approve",
        "advance_rate": 0.70,
        "limit": limit,
        "fee_rate": 0.009,
        "apr": 0.1095,
        "risk_score": 0.003,
        "reasons": ["Buyer confirmed invoice"],
        "decision_id": "dec_restart",
        "model_version": "pd-lgbm-0.1.0",
        "policy_version": "policy-0.1.0",
    }


def decision_hash(d: dict) -> str:
    return canonical_hash(PolicyDecision.model_validate(d).model_dump(mode="json", exclude={"decision_hash"}))


def open_receivable(client: TestClient) -> None:
    register = {
        "idempotency_key": "restart:register",
        "invoice_id": "inv_restart",
        "invoice_fingerprint": FP,
        "doc_hash": "sha256:restart",
        "face_value": "749000.00",
        "currency": "THB",
        "due_date": "2026-11-15",
        "seller": "SELLER:siam-fresh-pack",
    }
    assert client.post("/wallet/register", json=register, headers=AGENT).json()["status"] == "executed"
    d = decision()
    approve = {
        "idempotency_key": "restart:approve",
        "decision_id": "dec_restart",
        "decision": d,
        "decision_hash": decision_hash(d),
        "invoice_fingerprint": FP,
        "limit": "524300.00",
        "fee_rate": 0.009,
        "model_version": "pd-lgbm-0.1.0",
        "policy_version": "policy-0.1.0",
    }
    assert client.post("/wallet/approve", json=approve, headers=RISK_ORACLE).json()["status"] == "executed"


def draw(client: TestClient, amount: str, key: str) -> dict:
    """Draws against the approved decision, so the decision hash matches the one approved at TX-2."""
    d = decision()
    h = decision_hash(d)
    body = {
        "decision": {**d, "decision_hash": h},
        "payee": "SELLER:siam-fresh-pack",
        "amount": amount,
        "currency": "THB",
        "invoice_id": "inv_restart",
        "idempotency_key": key,
        "decision_id": "dec_restart",
        "decision_hash": h,
        "invoice_fingerprint": FP,
        "apr": 0.1095,
        "lender_id": "lender_a",
        "mandate_id": "mdt_001",
    }
    return client.post("/wallet/execute", json=body, headers=AGENT).json()


@pytest.fixture
def tokens(monkeypatch):
    monkeypatch.setenv("WALLET_OWNER_TOKEN", "owner-test-token")
    monkeypatch.setenv("WALLET_APPROVER_TOKEN", "approver-test-token")
    monkeypatch.setenv("WALLET_RISK_ORACLE_TOKEN", "risk-oracle-test-token")
    monkeypatch.setenv("WALLET_AGENT_TOKEN", "agent-test-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_startup_counts_what_the_chain_already_spent():
    service = WalletService(
        ChainStub(Decimal("2900000.00")),
        Store(),
        load_payees(CONFIG / "payees.json"),
        Decimal("0.003"),
        Clock(NOW),
    )
    bootstrap_demo(service)
    assert service.mandate is not None
    assert sum(amount for _, amount in service.store.spends) == Decimal("2900000.00")


def test_a_failed_read_at_startup_stops_the_wallet():
    class ChainDown(Exception):
        pass

    service = WalletService(
        ChainStub(ChainDown("rpc down")),
        Store(),
        load_payees(CONFIG / "payees.json"),
        Decimal("0.003"),
        Clock(NOW),
    )
    with pytest.raises(ChainDown):
        bootstrap_demo(service)


def test_a_restarted_wallet_refuses_a_draw_that_the_chain_total_puts_over_the_cap(tokens):
    service = build_service(clock=Clock(NOW))  # the mock ledger, which starts with nothing spent
    bootstrap_demo(service)
    # The restarted store is empty. The chain has already counted THB 2.9M in the last 24h.
    service.seed_spend(Decimal("2900000.00"))
    client = TestClient(create_app(service))
    open_receivable(client)

    over = draw(client, "524300.00", "restart:over")
    assert over["status"] == "blocked"
    assert over["block_reason"] == "DailyCapExceeded"
    assert over["chain_ref"] is None  # refused off-chain, so nothing was sent

    fits = draw(client, "100000.00", "restart:fits")  # 2.9M + 0.1M is exactly the THB 3M cap
    assert fits["status"] == "executed", fits
    assert service.ledger.rolling_spend() == Decimal("100000.00")
