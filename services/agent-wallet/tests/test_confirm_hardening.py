"""Human-approval path for draws the ledger queued (amount at or above the review threshold)."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from tests.test_api_flow import (
    APPROVER,
    CANARY,
    NOW,
    OWNER,
    Clock,
    decision_dict,
    execute_body,
    open_receivable,
)

from app.main import bootstrap_demo, build_service, create_app
from app.settings import get_settings

BIG = "980000.00"  # at or above the THB 837,500 review threshold


@pytest.fixture
def wallet(monkeypatch):
    monkeypatch.setenv("WALLET_OWNER_TOKEN", "owner-test-token")
    monkeypatch.setenv("WALLET_APPROVER_TOKEN", "approver-test-token")
    monkeypatch.setenv("WALLET_RISK_ORACLE_TOKEN", "risk-oracle-test-token")
    monkeypatch.setenv("WALLET_AGENT_TOKEN", "agent-test-token")
    monkeypatch.setenv("AGENT_CANARY", CANARY)
    get_settings.cache_clear()
    clock = Clock(NOW)
    service = build_service(clock=clock)
    bootstrap_demo(service)
    client = TestClient(create_app(service), headers={"X-Agent-Token": "agent-test-token"})
    yield client, service, clock
    get_settings.cache_clear()


def queue_big_draw(client, key: str = "fl_1:big") -> str:
    open_receivable(client, face="1400000.00", limit=BIG)
    body = execute_body(amount=BIG, key=key, decision=decision_dict(BIG))
    pending = client.post("/wallet/execute", json=body).json()
    assert pending["status"] == "pending_approval", pending
    return pending["tx_id"]


def confirm(client, tx_id: str, approve: bool = True) -> dict:
    return client.post(f"/wallet/confirm/{tx_id}", json={"approve": approve}, headers=APPROVER).json()


def test_queued_draw_is_listed_for_the_approver_with_amount_payee_and_expiry(wallet):
    client, service, _ = wallet
    tx_id = queue_big_draw(client)
    [item] = client.get("/wallet/holds", headers=APPROVER).json()["holds"]
    assert item["kind"] == "chain_pending"
    assert (item["tx_id"], item["amount"]) == (tx_id, BIG)
    assert item["payee_address"] == service.payees["SELLER:siam-fresh-pack"].address
    assert item["expires_at"] == (NOW + timedelta(hours=24)).isoformat()


def test_agent_cannot_route_around_the_approver_with_a_smaller_draw(wallet):
    """The large draw waits for a human; a 500,000 draw (below the threshold) on the same invoice is refused.
    Before, it was refused as AlreadyDrawn, which also left a declined invoice impossible to redraw."""
    client, service, _ = wallet
    queue_big_draw(client)
    small = execute_body(amount="500000.00", key="fl_1:small", decision=decision_dict(BIG))
    result = client.post("/wallet/execute", json=small).json()
    assert (result["status"], result["block_reason"]) == ("blocked", "ApprovalPending")
    assert result["chain_ref"] is None
    assert service.ledger.balances.get(service.payees["SELLER:siam-fresh-pack"].address.lower(), 0) == 0


def test_queued_draw_expires_after_24_hours_and_is_dropped_on_the_ledger(wallet):
    client, service, clock = wallet
    tx_id = queue_big_draw(client)
    clock.now = NOW + timedelta(hours=24, minutes=1)
    expired = confirm(client, tx_id)
    assert (expired["status"], expired["block_reason"]) == ("blocked", "ApprovalExpired")
    assert expired["chain_ref"].startswith("mock:0x")  # the decline went to the ledger
    assert service.ledger.pending == {}
    assert confirm(client, tx_id)["block_reason"] == "NotPending"


def test_decline_clears_the_ledger_queue_and_frees_the_receivable(wallet):
    client, service, _ = wallet
    tx_id = queue_big_draw(client)
    declined = confirm(client, tx_id, approve=False)
    assert declined["block_reason"] == "ApprovalDeclined"
    assert service.ledger.pending == {}
    retry = client.post(
        "/wallet/execute", json=execute_body(amount=BIG, key="fl_1:big-2", decision=decision_dict(BIG))
    ).json()
    assert retry["status"] == "pending_approval", retry["block_reason"]  # a fresh draft goes back to a human


def test_confirm_while_paused_can_be_retried_after_unpause(wallet):
    """A confirm that reverts on the ledger leaves the draw queued, so the approver can try again."""
    client, _, _ = wallet
    tx_id = queue_big_draw(client)
    assert client.post("/wallet/pause", headers=APPROVER).json()["status"] == "executed"
    paused = confirm(client, tx_id)
    assert (paused["status"], paused["block_reason"]) == ("blocked", "Paused")
    assert client.post("/wallet/unpause", headers=OWNER).json()["status"] == "executed"
    assert confirm(client, tx_id)["status"] == "executed"


def test_confirmed_draw_is_recorded_so_settlement_flags_and_redraws_work(wallet):
    client, service, _ = wallet
    tx_id = queue_big_draw(client)
    assert confirm(client, tx_id)["status"] == "executed"
    fact = next(iter(service.store.receivables.values()))
    assert fact.drawn_amount == Decimal(BIG)
    again = client.post(
        "/wallet/execute", json=execute_body(amount=BIG, key="fl_1:big-3", decision=decision_dict(BIG))
    ).json()
    assert again["block_reason"] == "AlreadyDrawn"
    assert again["chain_ref"] is None  # stopped off-chain, nothing sent
    short = client.post(
        "/wallet/settle",
        json={
            "idempotency_key": "fl_1:settle",
            "invoice_id": "inv_1",
            "invoice_fingerprint": fact_fp(service),
            "amount_paid": "500000.00",
        },
    ).json()
    assert "SHORT_PAID" in {c["code"] for c in short["checks"]}


def fact_fp(service) -> str:
    return next(iter(service.store.receivables))


def test_mock_ledger_decline_drops_the_pending_draw_like_agentwallet_confirm_false():
    from tests.test_mock_ledger import NO_FEES, approve, draw, make_ledger, register

    ledger, _ = make_ledger()
    register(ledger, face="1400000.00")
    approve(ledger, limit=BIG)
    pending = ledger.execute(draw(amount=Decimal(BIG), **NO_FEES))
    ledger.pause(True)
    assert ledger.confirm(pending.pending_id, approve=False).revert_reason == "Paused"
    ledger.pause(False)
    assert ledger.confirm(pending.pending_id, approve=False).ok
    assert ledger.confirm(pending.pending_id).revert_reason == "NotPending"


def test_approval_eval_cases_all_pass():
    """eval/approval_cases.jsonl: every approval-path attack is caught and every benign case completes."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
    from run_eval import evaluate, run_case

    path = Path(__file__).resolve().parents[1] / "eval" / "approval_cases.jsonl"
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    failures = [(c["id"], evaluate(c, run_case(c, CANARY, False))[1]) for c in cases]
    assert [f for f in failures if f[1] != "ok"] == []
