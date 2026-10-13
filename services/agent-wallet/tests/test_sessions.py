"""Scoped agent session keys: every scope rule that refuses a call has a test."""

# ruff: noqa: F811 - `client` is a pytest fixture imported from test_api_flow
import json
from datetime import timedelta
from pathlib import Path

from test_api_flow import (  # noqa: F401 - fixture
    APPROVER,
    FP,
    OWNER,
    client,
    decision_dict,
    execute_body,
    open_receivable,
    register_body,
)

FP2 = "0x" + "22" * 32
MANDATE = Path(__file__).resolve().parents[1] / "config" / "mandate.demo.json"


def issue(client, **grant) -> dict:
    body = {
        "actions": ["register", "execute", "settle"],
        "budget": "600000.00",
        "max_per_tx": "600000.00",
        **grant,
    }
    response = client.post("/wallet/session", json=body, headers=OWNER)
    assert response.status_code == 200, response.text
    return response.json()


def as_session(token: str) -> dict:
    return {"X-Agent-Session": token, "X-Agent-Token": ""}


def draw(client, token: str, **overrides) -> dict:
    body = {**execute_body(), **overrides}
    return client.post("/wallet/execute", json=body, headers=as_session(token)).json()


def test_session_key_draws_and_counts_against_its_budget(client):
    open_receivable(client)
    session = issue(client)
    out = draw(client, session["token"])
    assert out["status"] == "executed", out
    replay = draw(client, session["token"])  # same idempotency key: replayed, not charged twice
    assert any(c["code"] == "IdempotentReplay" for c in replay["checks"])
    listed = client.get("/wallet/sessions", headers=APPROVER).json()["sessions"][0]
    assert listed["spent"] == "524300.00" and listed["uses"] == 1
    assert "token" not in listed  # only a hash of the token is kept


def test_budget_exceeded_on_the_next_draw(client):
    open_receivable(client)
    session = issue(client)
    assert draw(client, session["token"])["status"] == "executed"
    second = draw(
        client, session["token"], amount="100000.00", invoice_fingerprint=FP2, idempotency_key="s:2"
    )
    assert second["status"] == "blocked" and second["block_reason"] == "SessionBudgetExceeded"
    assert second["checks"][0]["layer"] == "SK"


def test_per_draw_cap(client):
    open_receivable(client)
    session = issue(client, max_per_tx="500000.00")
    assert draw(client, session["token"])["block_reason"] == "SessionTxCapExceeded"


def test_expired_session_is_refused(client):
    open_receivable(client)
    session = issue(client, ttl_minutes=15)
    client.app.state.wallet.clock.now += timedelta(minutes=16)
    assert draw(client, session["token"])["block_reason"] == "SessionExpired"


def test_approver_can_revoke_at_once(client):
    open_receivable(client)
    session = issue(client)
    revoked = client.post(f"/wallet/session/{session['session_id']}/revoke", headers=APPROVER)
    assert revoked.status_code == 200
    assert draw(client, session["token"])["block_reason"] == "SessionRevoked"


def test_action_outside_the_grant(client):
    session = issue(client, actions=["execute"])
    out = client.post("/wallet/register", json=register_body(), headers=as_session(session["token"])).json()
    assert out["block_reason"] == "SessionActionNotAllowed"


def test_intent_bound_session_only_touches_its_invoice(client):
    open_receivable(client)
    session = issue(client, invoice_fingerprints=[FP2.upper().replace("0X", "0x")])
    assert draw(client, session["token"])["block_reason"] == "SessionInvoiceNotAllowed"


def test_new_mandate_voids_older_sessions(client):
    open_receivable(client)
    session = issue(client)
    mandate = {**json.loads(MANDATE.read_text(encoding="utf-8")), "version": 2}
    activated = client.post(
        "/wallet/mandate/activate", json={"mandate_id": "mdt_001", "mandate": mandate}, headers=OWNER
    )
    assert activated.status_code == 200, activated.text
    assert draw(client, session["token"])["block_reason"] == "SessionMandateChanged"


def test_session_above_the_mandate_caps_is_refused(client):
    response = client.post(
        "/wallet/session",
        json={"actions": ["execute"], "budget": "9000000.00", "max_per_tx": "100.00"},
        headers=OWNER,
    )
    assert response.status_code == 422


def test_only_the_owner_issues_and_unknown_tokens_are_403(client):
    body = {"actions": ["execute"], "budget": "100.00", "max_per_tx": "100.00"}
    assert client.post("/wallet/session", json=body, headers=APPROVER).status_code == 403
    assert client.post("/wallet/session", json=body).status_code == 403  # agent token only
    response = client.post("/wallet/execute", json=execute_body(), headers=as_session("sk_forged"))
    assert response.status_code == 403


def test_refusals_are_in_the_audit_log(client):
    open_receivable(client)
    session = issue(client, max_per_tx="500000.00")
    draw(client, session["token"])
    audit = client.get("/wallet/audit/inv_1").json()
    actors = {e["actor"] for e in audit["entries"]}
    assert session["session_id"] in actors and audit["verified"]
