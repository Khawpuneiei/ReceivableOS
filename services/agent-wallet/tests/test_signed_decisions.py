"""Signed credit decisions at approval (TX-2): each refusal has a test."""

# ruff: noqa: F811 - `client` is a pytest fixture imported from test_api_flow
import subprocess
import sys
from pathlib import Path

import pytest
from Crypto.PublicKey import ECC
from test_api_flow import (  # noqa: F401 - fixture
    FP,
    approve_body,
    client,
    decision_dict,
    execute_body,
    hash_of,
    register_body,
)

from app.guard.signatures import DecisionSigners, sign

ORACLE = {"X-Risk-Oracle-Token": "risk-oracle-test-token"}
KEY = ECC.generate(curve="ed25519")
PEM = KEY.export_key(format="PEM")
ATTACKER_PEM = ECC.generate(curve="ed25519").export_key(format="PEM")


@pytest.fixture
def signed(client):
    public = KEY.public_key().export_key(format="raw")
    client.app.state.wallet.decision_signers = DecisionSigners(enforce=True, keys={"policy-ai": public})
    assert client.post("/wallet/register", json=register_body()).json()["status"] == "executed"
    return client


def approve(client, decision: dict, signature: str | None) -> dict:
    headers = {**ORACLE, **({"X-Decision-Signature": signature} if signature else {})}
    body = approve_body(decision, key=f"approve:{signature}")  # one idempotency key per attempt
    return client.post("/wallet/approve", json=body, headers=headers).json()


def test_signed_decision_is_approved_and_drawn(signed):
    decision = decision_dict()
    out = approve(signed, decision, sign(PEM, "policy-ai", hash_of(decision), FP))
    assert out["status"] == "executed", out
    assert any(c["code"] == "DecisionSigned" and c["passed"] for c in out["checks"])
    assert signed.post("/wallet/execute", json=execute_body()).json()["status"] == "executed"


def test_unsigned_decision_is_refused_when_enforced(signed):
    out = approve(signed, decision_dict(), None)
    assert out["status"] == "blocked" and out["block_reason"] == "DecisionUnsigned"


def test_risk_oracle_token_alone_cannot_approve_its_own_decision(signed):
    """Stolen risk-oracle token, a self-made decision with a bigger limit, signed with the attacker's key."""
    decision = decision_dict(limit="700000.00")
    forged = sign(ATTACKER_PEM, "policy-ai", hash_of(decision), FP)
    assert approve(signed, decision, forged)["block_reason"] == "DecisionSignatureInvalid"
    unknown = sign(ATTACKER_PEM, "attacker", hash_of(decision), FP)
    assert approve(signed, decision, unknown)["block_reason"] == "DecisionSignerUnknown"


def test_signature_cannot_be_replayed_onto_another_invoice(signed):
    decision = decision_dict()
    for_other_invoice = sign(PEM, "policy-ai", hash_of(decision), "0x" + "99" * 32)
    assert approve(signed, decision, for_other_invoice)["block_reason"] == "DecisionSignatureInvalid"


def test_signature_for_another_decision_is_refused(signed):
    original, raised = decision_dict(), decision_dict(limit="600000.00")
    reused = sign(PEM, "policy-ai", hash_of(original), FP)
    assert approve(signed, raised, reused)["block_reason"] == "DecisionSignatureInvalid"


@pytest.mark.parametrize("header", ["garbage", "ed25519:policy-ai:not-base64!!", "rsa:policy-ai:AAAA"])
def test_malformed_signature_header(signed, header):
    assert approve(signed, decision_dict(), header)["block_reason"] == "DecisionSignatureInvalid"


def test_not_enforced_still_checks_a_signature_that_is_sent(client):
    assert client.post("/wallet/register", json=register_body()).json()["status"] == "executed"
    decision = decision_dict()
    bad = sign(ATTACKER_PEM, "policy-ai", hash_of(decision), FP)
    assert approve(client, decision, bad)["block_reason"] == "DecisionSignerUnknown"
    assert approve(client, decision, None)["status"] == "executed"  # default config: unsigned still works


def test_keygen_and_sign_script(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "decision_keys.py"
    pem = tmp_path / "signer.pem"
    out = subprocess.run(
        [sys.executable, str(script), "keygen", "--key-id", "k1", "--out", str(pem)],
        capture_output=True,
        text=True,
        check=True,
    )
    public = bytes.fromhex(__import__("json").loads(out.stdout)["signers"]["k1"])
    header = subprocess.run(
        [
            sys.executable,
            str(script),
            "sign",
            "--key",
            str(pem),
            "--key-id",
            "k1",
            "--decision-hash",
            "0x" + "ab" * 32,
            "--fingerprint",
            FP,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    signers = DecisionSigners(enforce=True, keys={"k1": public})
    assert signers.check(header, "0x" + "ab" * 32, FP) is None
