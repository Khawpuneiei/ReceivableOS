"""/flow/attack/{case}: each attack builds a fresh receivable, then makes one bad wallet call.

Fake services as in test_flow.py. The checks are on what the orchestrator sends (the one wrong field per
attack, fresh fingerprints, no TX-2 behind an unapproved draw) and that the wallet's answer is passed through.
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from test_flow import Services, wallet_result, wire

from app import main
from app.main import app


class AttackServices(Services):
    """Blocks every draw with the given reason, the way the real guard answers."""

    def __init__(self, decision_kind="approve", block="AprAboveMandate"):
        super().__init__(decision_kind)
        self.block = block

    def handler(self, request: httpx.Request) -> httpx.Response:
        response = super().handler(request)
        if request.url.path == "/wallet/execute":
            blocked = wallet_result("blocked", self.block)
            blocked["checks"] = [{"layer": "L3", "code": self.block, "passed": False}]
            return httpx.Response(200, json=blocked)
        return response


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "WALLET_AGENT_TOKEN", "agent")
    monkeypatch.setattr(main, "WALLET_RISK_ORACLE_TOKEN", "oracle")
    monkeypatch.setattr(main, "ORCHESTRATOR_TOKEN", "caller")
    return TestClient(app, headers={"X-Orchestrator-Token": "caller"})


def attack(client, case: str) -> dict:
    r = client.post(f"/flow/attack/{case}")
    assert r.status_code == 200, r.text
    return r.json()


def test_a3_attacks_an_approved_receivable_with_only_the_apr_wrong(client, monkeypatch):
    services = AttackServices()
    wire(monkeypatch, services)
    out = attack(client, "a3")
    assert services.paths() == ["/wallet/register", "/policy/decide", "/wallet/approve", "/wallet/execute"]
    _, body = services.call("/wallet/execute")
    assert (
        body["apr"] == "0.19" and body["amount"] == "524300.00" and body["payee"] == "SELLER:siam-fresh-pack"
    )
    assert out["status"] == "blocked" and out["wallet"]["block_reason"] == "AprAboveMandate"
    assert out["stopped_by"] == "Wallet guard L3" and out["live"] is True


def test_a4_draws_the_full_face_value(client, monkeypatch):
    services = AttackServices(block="AmountAboveLimit")
    wire(monkeypatch, services)
    attack(client, "A4")
    assert services.call("/wallet/execute")[1]["amount"] == "749000.00"


def test_a1_pays_the_attacker_with_no_approval_behind_it(client, monkeypatch):
    services = AttackServices(decision_kind="review", block="NotApproved")
    wire(monkeypatch, services)
    out = attack(client, "A1")
    assert "/wallet/approve" not in services.paths()
    _, decide = services.call("/policy/decide")
    assert decide["invoice"]["injection_flags"] == ["VISIBLE_INSTRUCTION"]
    assert services.call("/wallet/execute")[1]["payee"] == "0xAttacker"
    assert out["policy"]["decision"] == "review"


def test_a5_sends_an_expired_kyb_profile_and_never_approves(client, monkeypatch):
    services = AttackServices(decision_kind="reject", block="NotApproved")
    wire(monkeypatch, services)
    attack(client, "A5")
    _, decide = services.call("/policy/decide")
    assert decide["supplier_profile"]["kyc_valid"] is False
    assert "/wallet/approve" not in services.paths()


class RegisterTwice(AttackServices):
    """The first registration goes through; the second gets `second`."""

    def __init__(self, second: dict):
        super().__init__()
        self.answers = [wallet_result(), second]

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/wallet/register":
            self.register = self.answers.pop(0)
        return super().handler(request)


def test_a2_registers_the_same_fingerprint_twice_with_a_new_doc_hash(client, monkeypatch):
    services = RegisterTwice(wallet_result("blocked", "DuplicateReceivable"))
    wire(monkeypatch, services)
    out = attack(client, "A2")
    first, second = [body for path, _, body in services.calls if path == "/wallet/register"]
    assert first["invoice_fingerprint"] == second["invoice_fingerprint"]
    assert first["doc_hash"] != second["doc_hash"]
    assert out["wallet"]["block_reason"] == "DuplicateReceivable"
    assert out["status"] == "blocked" and out["stopped_by"] == "Registry (on-chain duplicate check)"


def test_a2_that_registers_twice_is_reported_as_not_stopped(client, monkeypatch):
    wire(monkeypatch, RegisterTwice(wallet_result()))
    out = attack(client, "A2")
    assert out["status"] == "executed" and out["stopped_by"] == "not stopped"


def test_a2_blocked_by_another_check_names_that_check(client, monkeypatch):
    blocked = wallet_result("blocked", "InjectionSuspected")
    blocked["checks"] = [{"layer": "L2", "code": "InjectionSuspected", "passed": False}]
    wire(monkeypatch, RegisterTwice(blocked))
    assert attack(client, "A2")["stopped_by"] == "Wallet guard L2"


def test_a2_whose_first_registration_fails_is_a_setup_error(client, monkeypatch):
    services = AttackServices()
    services.register = wallet_result("blocked", "PayeeNotAllowed")
    wire(monkeypatch, services)
    r = client.post("/flow/attack/A2")
    assert r.status_code == 502 and "PayeeNotAllowed" in r.json()["detail"]


def test_every_attack_uses_a_fresh_fingerprint(client, monkeypatch):
    services = AttackServices()
    wire(monkeypatch, services)
    attack(client, "A3")
    attack(client, "A3")
    fps = [body["invoice_fingerprint"] for path, _, body in services.calls if path == "/wallet/register"]
    assert len(set(fps)) == 2


def test_an_attack_that_is_not_stopped_is_reported_as_such(client, monkeypatch):
    services = Services()  # a wallet that executes everything
    wire(monkeypatch, services)
    out = attack(client, "A3")
    assert out["status"] == "executed" and out["stopped_by"] == "not stopped"


def test_unknown_attack_is_404(client):
    assert client.post("/flow/attack/A9").status_code == 404


def test_an_attack_without_the_caller_token_is_refused(client, monkeypatch):
    monkeypatch.setattr(main, "_client", lambda: pytest.fail("no service may be called"))
    assert TestClient(app).post("/flow/attack/A1").status_code == 403
    wrong = {"X-Orchestrator-Token": "wrong"}
    assert TestClient(app).post("/flow/attack/A1", headers=wrong).status_code == 403
