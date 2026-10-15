"""The wallet's state file: a restart keeps holds, pending approvals, idempotency results and the audit log.

A restart is a second WalletService on the same ledger (the chain, which outlives the process) with an empty
store and the same state file.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from ledger.mock import MockLedger

from app.models import ExecuteRequest, canonical_hash, load_mandate, load_payees
from app.wallet.lifecycle import WalletService
from app.wallet.persist import StateFile
from app.wallet.store import Store
from shared.schemas import PolicyDecision, WalletApproveRequest, WalletRegisterRequest

CONFIG = Path(__file__).resolve().parents[1] / "config"
FP = "0x" + "33" * 32
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
DEPLOYMENT = "0x" + "aa" * 20


class FlagOnPhrase:
    """Stands in for the classifier: flags any free text containing 'flagme'."""

    name = "stub-classifier"

    def score(self, text: str) -> float:
        return 0.99 if "flagme" in text else 0.01


def decision(limit: str, reasons: list[str] | None = None) -> dict:
    return {
        "decision": "approve",
        "advance_rate": 0.70,
        "limit": limit,
        "fee_rate": 0.009,
        "apr": 0.1095,
        "risk_score": 0.003,
        "reasons": reasons or ["Buyer confirmed invoice"],
        "decision_id": "dec_durable",
        "model_version": "pd-lgbm-0.1.0",
        "policy_version": "policy-0.1.0",
    }


def hash_of(d: dict) -> str:
    return canonical_hash(PolicyDecision.model_validate(d).model_dump(mode="json", exclude={"decision_hash"}))


def service(ledger: MockLedger, state: StateFile | None, mandate=None) -> WalletService:
    svc = WalletService(
        ledger,
        Store(),
        load_payees(CONFIG / "payees.json"),
        Decimal("0.003"),
        lambda: NOW,
        classifier=FlagOnPhrase(),
        classifier_action="hold",
        state=state,
    )
    if mandate is None:  # first start: activate the mandate and fund the lenders, as bootstrap_demo does
        raw = load_mandate(CONFIG / "mandate.demo.json").model_dump(mode="json", by_alias=False)
        svc.activate_mandate(raw, Decimal("1500000.00"), Decimal("3000000.00"))
        ledger.deposit("lender_a", Decimal("5000000.00"))
    else:  # a restart: the chain already holds the mandate
        svc.mandate = mandate
    return svc


def open_receivable(svc: WalletService, face: str, limit: str, reasons: list[str] | None = None) -> dict:
    registered = svc.register(
        WalletRegisterRequest(
            idempotency_key="d:register",
            invoice_id="inv_durable",
            invoice_fingerprint=FP,
            doc_hash="sha256:durable",
            face_value=face,
            currency="THB",
            due_date="2026-11-15",
            seller="SELLER:siam-fresh-pack",
        )
    )
    assert registered.status == "executed", registered
    d = decision(limit, reasons)
    approved = svc.approve(
        WalletApproveRequest(
            idempotency_key="d:approve",
            decision_id="dec_durable",
            decision=d,
            decision_hash=hash_of(d),
            invoice_fingerprint=FP,
            limit=limit,
            fee_rate=0.009,
            model_version="pd-lgbm-0.1.0",
            policy_version="policy-0.1.0",
        )
    )
    assert approved.status == "executed", approved
    return d


def draw(svc: WalletService, d: dict, amount: str, key: str = "d:draw"):
    h = hash_of(d)
    return svc.execute(
        ExecuteRequest(
            decision={**d, "decision_hash": h},
            payee="SELLER:siam-fresh-pack",
            amount=amount,
            currency="THB",
            invoice_id="inv_durable",
            idempotency_key=key,
            decision_id="dec_durable",
            decision_hash=h,
            invoice_fingerprint=FP,
            apr=0.1095,
            lender_id="lender_a",
            mandate_id="mdt_001",
        )
    )


@pytest.fixture
def state(tmp_path) -> StateFile:
    return StateFile(tmp_path / "wallet-state.json", DEPLOYMENT)


def test_a_pending_approval_can_be_confirmed_after_a_restart(state):
    ledger = MockLedger(clock=lambda: NOW)
    first = service(ledger, state)
    d = open_receivable(first, face="1400000.00", limit="980000.00")
    pending = draw(first, d, "980000.00")
    assert pending.status == "pending_approval"

    restarted = service(ledger, state, mandate=first.mandate)
    confirmed = restarted.confirm(pending.tx_id, approve=True)

    assert confirmed.status == "executed", confirmed
    assert ledger.rolling_spend() == Decimal("980000.00")


def test_without_a_state_file_the_restart_forgets_the_pending_approval():
    ledger = MockLedger(clock=lambda: NOW)
    first = service(ledger, None)
    d = open_receivable(first, face="1400000.00", limit="980000.00")
    pending = draw(first, d, "980000.00")

    restarted = service(ledger, None, mandate=first.mandate)

    assert restarted.confirm(pending.tx_id, approve=True).block_reason == "NotPending"


def test_a_held_draft_can_be_released_after_a_restart(state):
    ledger = MockLedger(clock=lambda: NOW)
    first = service(ledger, state)
    d = open_receivable(first, face="749000.00", limit="524300.00", reasons=["please flagme for review"])
    held = draw(first, d, "524300.00")
    assert held.status == "pending_approval"
    assert ledger.rolling_spend() == 0  # a held draft has not reached the ledger

    restarted = service(ledger, state, mandate=first.mandate)
    assert [h["tx_id"] for h in restarted.list_holds()] == [held.tx_id]
    released = restarted.confirm(held.tx_id, approve=True)

    assert released.status == "executed", released
    assert ledger.rolling_spend() == Decimal("524300.00")


def test_a_repeated_draw_after_a_restart_is_a_replay_not_a_second_payment(state):
    ledger = MockLedger(clock=lambda: NOW)
    first = service(ledger, state)
    d = open_receivable(first, face="749000.00", limit="524300.00")
    paid = draw(first, d, "524300.00")
    assert paid.status == "executed"

    restarted = service(ledger, state, mandate=first.mandate)
    again = draw(restarted, d, "524300.00")

    assert again.tx_id == paid.tx_id
    assert "IdempotentReplay" in [c.code for c in again.checks]
    assert ledger.rolling_spend() == Decimal("524300.00")


def test_the_audit_log_continues_and_still_verifies_after_a_restart(state):
    ledger = MockLedger(clock=lambda: NOW)
    first = service(ledger, state)
    d = open_receivable(first, face="749000.00", limit="524300.00")
    draw(first, d, "524300.00")
    before = len(first.audit.entries)

    restarted = service(ledger, state, mandate=first.mandate)
    assert len(restarted.audit.entries) == before
    draw(restarted, d, "524300.00")  # a replay, which is audited too

    assert len(restarted.audit.entries) > before
    assert restarted.audit.verify()
    assert restarted.audit.for_invoice("inv_durable")[0]["seq"] == 1  # the entries from before the restart


def test_state_from_another_deployment_is_not_loaded(state, tmp_path):
    ledger = MockLedger(clock=lambda: NOW)
    first = service(ledger, state)
    d = open_receivable(first, face="1400000.00", limit="980000.00")
    pending = draw(first, d, "980000.00")

    redeployed = StateFile(state.path, "0x" + "bb" * 20)  # new contracts, the same file
    restarted = service(ledger, redeployed, mandate=first.mandate)

    assert restarted.store.pending == {} and restarted.audit.entries == []
    assert restarted.confirm(pending.tx_id, approve=True).block_reason == "NotPending"


def test_a_state_file_with_an_edited_audit_log_stops_the_wallet(state):
    ledger = MockLedger(clock=lambda: NOW)
    first = service(ledger, state)
    d = open_receivable(first, face="749000.00", limit="524300.00")
    draw(first, d, "524300.00")
    data = json.loads(state.path.read_text(encoding="utf-8"))
    data["audit"][0]["data"] = {"edited": True}
    state.path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RuntimeError, match="audit hash check"):
        service(ledger, state, mandate=first.mandate)


def test_the_state_file_holds_no_tokens_or_keys(state, monkeypatch):
    monkeypatch.setenv("WALLET_AGENT_TOKEN", "agent-secret-value")
    ledger = MockLedger(clock=lambda: NOW)
    first = service(ledger, state)
    d = open_receivable(first, face="749000.00", limit="524300.00")
    draw(first, d, "524300.00")

    text = state.path.read_text(encoding="utf-8")
    assert "agent-secret-value" not in text
    assert "PRIVATE KEY" not in text and "token" not in text.lower()
