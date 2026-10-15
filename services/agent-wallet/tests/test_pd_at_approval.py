"""PD is not on chain, so the risk oracle's TX-2 approval refuses a decision above the mandate's PD ceiling.

Red-team cases W07, S15 and S16 paid out with the off-chain guard bypassed (eval/REDTEAM.md, chain alone).
With the ceiling bound at approval there is no on-chain approval, so the bypassed draw reverts NotApproved.
"""

# ruff: noqa: F811
import pytest
from fastapi.testclient import TestClient
from tests.test_api_flow import (
    NOW,
    Clock,
    approve_body,
    client,  # noqa: F401 - pytest fixture
    decision_dict,
    execute_body,
    register_body,
)

from app.main import bootstrap_demo, build_service, create_app
from app.settings import get_settings

TOKENS = {
    "WALLET_OWNER_TOKEN": "owner-test-token",
    "WALLET_APPROVER_TOKEN": "approver-test-token",
    "WALLET_RISK_ORACLE_TOKEN": "risk-oracle-test-token",
    "WALLET_AGENT_TOKEN": "agent-test-token",
}
ORACLE = {"X-Risk-Oracle-Token": "risk-oracle-test-token"}


def high_pd(risk: float = 0.08) -> dict:
    return {**decision_dict(), "risk_score": risk}


def test_approval_above_the_pd_ceiling_is_refused(client):
    assert client.post("/wallet/register", json=register_body()).json()["status"] == "executed"
    result = client.post("/wallet/approve", json=approve_body(high_pd()), headers=ORACLE).json()
    assert (result["status"], result["block_reason"]) == ("blocked", "PdAboveMandate")
    assert result["chain_ref"] is None  # nothing sent to the registry


def test_approval_at_the_pd_ceiling_passes(client):
    assert client.post("/wallet/register", json=register_body()).json()["status"] == "executed"
    result = client.post("/wallet/approve", json=approve_body(high_pd(0.05)), headers=ORACLE).json()
    assert result["status"] == "executed", result


@pytest.fixture
def demo_client(monkeypatch):
    for name, value in TOKENS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DEMO_MODE", "1")
    get_settings.cache_clear()
    service = build_service(clock=Clock(NOW))
    bootstrap_demo(service)
    yield TestClient(create_app(service), headers={"X-Agent-Token": "agent-test-token"})
    get_settings.cache_clear()


def test_bypassed_draw_on_a_high_pd_decision_reverts_on_chain(demo_client):
    client = demo_client
    client.post("/wallet/register", json=register_body())
    client.post("/wallet/approve", json=approve_body(high_pd()), headers=ORACLE)
    body = {**execute_body(decision=high_pd()), "skip_offchain_checks": True}
    result = client.post("/wallet/execute", json=body).json()
    assert (result["status"], result["block_reason"]) == ("blocked", "NotApproved")
    assert result["chain_ref"].startswith("mock:0x")  # the revert came from the ledger
