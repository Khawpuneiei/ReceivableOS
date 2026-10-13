"""Checks a wallet audit proof on screen, without trusting the wallet (RFC 9162, as in agent-wallet #58).

Written here from the RFC rather than imported from agent-wallet, so the screen is an independent verifier:
1. the entry's hash recomputes from its own contents and prev_hash (the entry was not edited);
2. the inclusion path leads from SHA-256(0x00 || entry hash) to the root (it is in the log);
3. `anchored` says whether that root was written on chain; before settlement it is the wallet's current root.
"""

import hashlib
import json


def _h(data: bytes) -> str:
    return "0x" + hashlib.sha256(data).hexdigest()


def _b(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str.removeprefix("0x"))


def entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return "0x" + hashlib.sha256((entry["prev_hash"] + canonical).encode("utf-8")).hexdigest()


def _node(left: str, right: str) -> str:
    return _h(b"\x01" + _b(left) + _b(right))


def included(leaf: str, index: int, size: int, path: list[str], root: str) -> bool:
    """RFC 9162 section 2.1.3.2."""
    if not 0 <= index < size:
        return False
    fn, sn, r = index, size - 1, leaf
    for p in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = _node(p, r)
            while not fn & 1 and fn != 0:
                fn >>= 1
                sn >>= 1
        else:
            r = _node(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r.lower() == root.lower()


def check(bundle: dict) -> list[str]:
    """Problems with a proof bundle in plain words; empty means the entry is in the log under that root."""
    entry = bundle["entry"]
    problems = []
    if entry_hash(entry) != entry["hash"]:
        problems.append("the entry does not match its own hash, so it was edited")
    leaf = _h(b"\x00" + _b(entry["hash"]))
    if not included(leaf, bundle["leaf_index"], bundle["tree_size"], bundle["proof"], bundle["root"]):
        problems.append("the proof does not lead to the log's root")
    return problems
