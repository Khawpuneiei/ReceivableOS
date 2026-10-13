"""GET /flow/audit/{audit_ref}/proof passes the wallet's Merkle proof through, or says why it cannot."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app

ENTRY = {"seq": 7, "audit_ref": "aud_7", "hash": "0x" + "ab" * 32, "prev_hash": "0x" + "00" * 32}
PROOF = {
    "entry": ENTRY,
    "leaf_index": 6,
    "tree_size": 8,
    "proof": ["0x" + "cd" * 32],
    "root": "0x" + "ef" * 32,
    "anchored": True,
    "chain_ref": "mock:0x01",
}


def wallet(proof_route: bool = True, entries: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/wallet/audit/ref/"):
            return httpx.Response(
                200, json={"entries": [ENTRY] if entries is None else entries, "verified": True}
            )
        if path == "/wallet/audit/proof/7" and proof_route:
            return httpx.Response(200, json=PROOF)
        return httpx.Response(404, json={"detail": "Not Found"})

    return handler


@pytest.fixture
def use(monkeypatch):
    def install(handler):
        monkeypatch.setattr(
            main, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        return TestClient(app)

    return install


def test_proof_is_passed_through_for_the_latest_entry_of_the_ref(use):
    r = use(wallet()).get("/flow/audit/aud_7/proof")
    assert r.status_code == 200
    body = r.json()
    assert body["seq"] == 7 and body["root"] == PROOF["root"] and body["entry"] == ENTRY


def test_a_wallet_without_merkle_proofs_gives_501(use):
    r = use(wallet(proof_route=False)).get("/flow/audit/aud_7/proof")
    assert r.status_code == 501 and "no Merkle" in r.json()["detail"]


def test_an_unknown_audit_ref_gives_404(use):
    r = use(wallet(entries=[])).get("/flow/audit/aud_404/proof")
    assert r.status_code == 404
