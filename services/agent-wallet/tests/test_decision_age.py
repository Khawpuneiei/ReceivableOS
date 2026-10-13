"""CLAUDE.md 5.4: a decision without valid_until is stale 15 minutes after its TX-2 approval.

A decision approved on chain and left unused must not be replayed hours later, when the buyer's risk or the
lender quotes may have changed. Policy-ai can extend the window by sending valid_until.
"""

from datetime import timedelta

from tests.test_api_flow import NOW, decision_dict, execute_body, open_receivable
from tests.test_confirm_hardening import wallet  # noqa: F401 - pytest fixture


def draw(client, key: str = "fl_1:draw", decision: dict | None = None) -> dict:
    return client.post("/wallet/execute", json=execute_body(key=key, decision=decision)).json()


def test_a_draw_within_15_minutes_of_the_approval_executes(wallet):  # noqa: F811
    client, _, clock = wallet
    open_receivable(client)
    clock.now = NOW + timedelta(minutes=14)
    assert draw(client)["status"] == "executed"


def test_a_draw_16_minutes_after_the_approval_is_stale_and_sends_nothing(wallet):  # noqa: F811
    client, service, clock = wallet
    open_receivable(client)
    clock.now = NOW + timedelta(minutes=16)
    result = draw(client)
    assert (result["status"], result["block_reason"]) == ("blocked", "DecisionStale")
    assert result["chain_ref"] is None
    assert service.ledger.balances.get(service.payees["SELLER:siam-fresh-pack"].address.lower(), 0) == 0


def test_valid_until_from_policy_replaces_the_15_minute_window(wallet):  # noqa: F811
    client, _, clock = wallet
    open_receivable(client)
    clock.now = NOW + timedelta(minutes=40)
    later = {**decision_dict(), "valid_until": (NOW + timedelta(hours=1)).isoformat()}
    assert draw(client, decision=later)["status"] == "executed"
