"""Merkle tree over the audit log, with inclusion proofs (RFC 9162, Certificate Transparency v2).

Owner: Agent AI engineer.

The hash chain proves the whole log is intact, but checking one entry needs every entry before it. The Merkle
root over the entry hashes is anchored on chain instead, so an auditor can check one invoice's entries with a
short proof (about log2(n) hashes) and the on-chain root, without seeing any other borrower's entries.

Domain separation as in RFC 9162: leaf = SHA-256(0x00 || entry_hash), node = SHA-256(0x01 || left || right).
The functions take and return 0x-prefixed hex strings. They have no wallet imports, so an auditor can copy
this file and verify a proof on their own.
"""

import hashlib


def _b(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str.removeprefix("0x"))


def _h(data: bytes) -> str:
    return "0x" + hashlib.sha256(data).hexdigest()


def leaf_hash(entry_hash: str) -> str:
    return _h(b"\x00" + _b(entry_hash))


def node_hash(left: str, right: str) -> str:
    return _h(b"\x01" + _b(left) + _b(right))


def _split(n: int) -> int:
    """The largest power of two strictly below n (n >= 2)."""
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def root(leaves: list[str]) -> str:
    """Merkle tree head over already-hashed leaves. The empty tree is SHA-256 of nothing."""
    if not leaves:
        return _h(b"")
    if len(leaves) == 1:
        return leaves[0]
    k = _split(len(leaves))
    return node_hash(root(leaves[:k]), root(leaves[k:]))


def proof(leaves: list[str], index: int) -> list[str]:
    """Audit path for leaves[index], ordered from the leaf up."""
    if not 0 <= index < len(leaves):
        raise IndexError("leaf index out of range")
    if len(leaves) == 1:
        return []
    k = _split(len(leaves))
    if index < k:
        return [*proof(leaves[:k], index), root(leaves[k:])]
    return [*proof(leaves[k:], index - k), root(leaves[:k])]


def verify(leaf: str, index: int, size: int, path: list[str], expected_root: str) -> bool:
    """RFC 9162 section 2.1.3.2: does `leaf` sit at `index` of a tree of `size` leaves with this root?"""
    if not 0 <= index < size:
        return False
    fn, sn, r = index, size - 1, leaf
    for p in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = node_hash(p, r)
            while not fn & 1 and fn != 0:
                fn >>= 1
                sn >>= 1
        else:
            r = node_hash(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r.lower() == expected_root.lower()
