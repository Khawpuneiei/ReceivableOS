"""Merkle anchoring of the audit log and per-entry inclusion proofs (RFC 9162)."""

# ruff: noqa: E501, F811 - long request bodies; `wallet` is a pytest fixture imported from test_audit

import copy
import hashlib
import sys
from pathlib import Path

import pytest
from test_audit import FP, open_and_draw, wallet  # noqa: F401 - fixture

from app.audit import merkle

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_audit_proof import check  # noqa: E402


def leaves(n: int) -> list[str]:
    return [merkle.leaf_hash("0x" + hashlib.sha256(str(i).encode()).hexdigest()) for i in range(n)]


@pytest.mark.parametrize("n", [1, 2, 3, 5, 8, 13])
def test_every_leaf_proves_for_odd_and_even_sizes(n):
    tree = leaves(n)
    root = merkle.root(tree)
    for i in range(n):
        path = merkle.proof(tree, i)
        assert len(path) <= max(1, (n - 1).bit_length())
        assert merkle.verify(tree[i], i, n, path, root)


def test_wrong_leaf_index_or_size_fails():
    tree = leaves(7)
    root, path = merkle.root(tree), merkle.proof(tree, 3)
    assert not merkle.verify(tree[4], 3, 7, path, root)  # another leaf
    assert not merkle.verify(tree[3], 2, 7, path, root)  # another position
    last = merkle.proof(tree, 6)
    assert merkle.verify(tree[6], 6, 7, last, root)
    assert not merkle.verify(tree[6], 6, 8, last, root)  # another tree size
    assert not merkle.verify(tree[3], 9, 7, path, root)  # out of range


def test_leaf_and_node_hashes_are_domain_separated():
    """A node can't be passed off as a leaf (the second-preimage trick RFC 9162 prefixes prevent)."""
    a, b = leaves(2)
    assert merkle.leaf_hash(merkle.node_hash(a, b)) != merkle.node_hash(a, b)


def settle(client):
    body = {
        "idempotency_key": "fl_1:settle",
        "invoice_id": "inv_1",
        "invoice_fingerprint": FP,
        "amount_paid": "749000.00",
    }
    return client.post("/wallet/settle", json=body).json()


def test_settlement_anchors_the_merkle_root_and_each_entry_proves(wallet):
    client, service = wallet
    assert open_and_draw(client)["status"] == "executed"
    assert settle(client)["status"] == "executed"
    anchored_root, size = service.ledger.anchors[-1]
    assert anchored_root == service.audit.merkle_root(size)
    for seq in range(1, size + 1):
        bundle = client.get(f"/wallet/audit/proof/{seq}").json()
        assert bundle["anchored"] and bundle["root"] == anchored_root
        assert check(bundle) == []


def test_edited_entry_fails_the_proof(wallet):
    client, _ = wallet
    open_and_draw(client)
    settle(client)
    bundle = client.get("/wallet/audit/proof/3").json()
    forged = copy.deepcopy(bundle)
    forged["entry"]["data"] = {"layer": "L3", "code": "AprAboveMandate", "passed": True}
    assert "entry hash does not match its contents" in check(forged)
    rehashed = copy.deepcopy(forged)  # the forger also recomputes the entry hash: now the path breaks
    body = {k: v for k, v in rehashed["entry"].items() if k != "hash"}
    from app.audit.log import _digest

    rehashed["entry"]["hash"] = _digest(rehashed["entry"]["prev_hash"], body)
    assert "inclusion proof does not lead to the root" in check(rehashed)


def test_entry_after_the_last_anchor_is_reported_unanchored(wallet):
    client, service = wallet
    open_and_draw(client)
    bundle = client.get(f"/wallet/audit/proof/{len(service.audit.entries)}").json()
    assert bundle["anchored"] is False
    assert check(bundle) == [
        "not anchored yet: the root is the wallet's current one, not one written on chain"
    ]


def test_on_demand_anchor_needs_owner_or_approver(wallet):
    client, service = wallet
    open_and_draw(client)
    assert client.post("/wallet/audit/anchor").status_code == 403
    response = client.post("/wallet/audit/anchor", headers={"X-Approver-Token": "approver-test-token"})
    assert response.status_code == 200 and response.json()["ok"]
    assert service.ledger.anchors[-1][0] == response.json()["root"]
    assert client.get("/wallet/audit/proof/1").json()["anchored"] is True


def test_unknown_entry_is_404(wallet):
    client, _ = wallet
    assert client.get("/wallet/audit/proof/999").status_code == 404
