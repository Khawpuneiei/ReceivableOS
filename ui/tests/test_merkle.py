"""The on-screen audit check accepts a real proof and catches an edited entry or a wrong root."""

import copy
import hashlib

import merkle


def _leaf(h: str) -> str:
    return "0x" + hashlib.sha256(b"\x00" + bytes.fromhex(h[2:])).hexdigest()


def _root(leaves: list[str]) -> str:
    if len(leaves) == 1:
        return leaves[0]
    k = 1
    while k * 2 < len(leaves):
        k *= 2
    return merkle._node(_root(leaves[:k]), _root(leaves[k:]))


def _proof(leaves: list[str], i: int) -> list[str]:
    if len(leaves) == 1:
        return []
    k = 1
    while k * 2 < len(leaves):
        k *= 2
    if i < k:
        return [*_proof(leaves[:k], i), _root(leaves[k:])]
    return [*_proof(leaves[k:], i - k), _root(leaves[:k])]


def _log(n: int) -> list[dict]:
    entries, prev = [], "0x" + "00" * 32
    for seq in range(1, n + 1):
        body = {"seq": seq, "action": "draw", "event": "EXECUTED", "data": {}, "prev_hash": prev}
        entry = {**body, "hash": merkle.entry_hash({**body, "hash": ""})}
        entries.append(entry)
        prev = entry["hash"]
    return entries


def _bundle(n: int, seq: int) -> dict:
    entries = _log(n)
    leaves = [_leaf(e["hash"]) for e in entries]
    return {
        "entry": entries[seq - 1],
        "leaf_index": seq - 1,
        "tree_size": n,
        "proof": _proof(leaves, seq - 1),
        "root": _root(leaves),
        "anchored": False,
    }


def test_a_real_proof_verifies_for_every_entry_of_odd_and_even_logs():
    for n in (1, 5, 8):
        for seq in range(1, n + 1):
            assert merkle.check(_bundle(n, seq)) == []


def test_an_edited_entry_or_a_wrong_root_fails_in_plain_words():
    edited = _bundle(5, 3)
    edited["entry"] = {**edited["entry"], "event": "BLOCKED"}
    assert merkle.check(edited) == ["the entry does not match its own hash, so it was edited"]
    wrong = copy.deepcopy(_bundle(5, 3))
    wrong["root"] = "0x" + "ff" * 32
    assert merkle.check(wrong) == ["the proof does not lead to the log's root"]
