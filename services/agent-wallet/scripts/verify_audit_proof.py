"""Check one audit entry against the anchored Merkle root, offline (an auditor's tool).

Fetches GET /wallet/audit/proof/{seq} (or reads the saved JSON), then checks, without trusting the wallet:
1. the entry's hash recomputes from its own contents and its prev_hash, so the entry was not edited;
2. the inclusion proof leads from that hash to the root (RFC 9162);
3. the root is the one anchored: compare the printed root and chain_ref with the AuditAnchored event on chain.

    python services/agent-wallet/scripts/verify_audit_proof.py --url http://127.0.0.1:8003 --seq 5
    python services/agent-wallet/scripts/verify_audit_proof.py --file proof.json
"""

import argparse
import json
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]

from app.audit import merkle  # noqa: E402
from app.audit.log import _digest  # noqa: E402


def check(bundle: dict) -> list[str]:
    """Problems found in a proof bundle; an empty list means it verifies."""
    entry = bundle["entry"]
    body = {k: v for k, v in entry.items() if k != "hash"}
    problems = []
    if _digest(entry["prev_hash"], body) != entry["hash"]:
        problems.append("entry hash does not match its contents")
    leaf = merkle.leaf_hash(entry["hash"])
    if not merkle.verify(leaf, bundle["leaf_index"], bundle["tree_size"], bundle["proof"], bundle["root"]):
        problems.append("inclusion proof does not lead to the root")
    if not bundle.get("anchored"):
        problems.append("not anchored yet: the root is the wallet's current one, not one written on chain")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8003")
    parser.add_argument("--seq", type=int)
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    if args.file:
        bundle = json.loads(args.file.read_text(encoding="utf-8"))
    else:
        import httpx

        bundle = httpx.get(f"{args.url}/wallet/audit/proof/{args.seq}", timeout=10).raise_for_status().json()
    problems = check(bundle)
    entry = bundle["entry"]
    print(f"entry {entry['seq']} {entry['action']}/{entry['event']} invoice {entry['invoice_id']}")
    print(f"tree size {bundle['tree_size']}  proof {len(bundle['proof'])} hashes  root {bundle['root']}")
    print(f"anchored {bundle['anchored']}  chain_ref {bundle['chain_ref']}")
    print("VERIFIED" if not problems else "FAILED: " + "; ".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
