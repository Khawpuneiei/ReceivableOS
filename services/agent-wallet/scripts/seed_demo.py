"""Idempotent demo setup against a running agent-wallet service (mock ledger). Owner: Agent AI engineer.

    python services/agent-wallet/scripts/seed_demo.py --url http://127.0.0.1:8003

It checks the service is up, re-activates the demo mandate with the owner token (activating the same mandate
again gives the same hash), and prints the payee registry and the mandate. Lender liquidity (TX-3) is seeded
when the service starts (bootstrap_demo, mock only), so this script does not deposit over HTTP.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

SERVICE = Path(__file__).resolve().parents[1]
CONFIG = SERVICE / "config"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.getenv("WALLET_URL", "http://127.0.0.1:8003"))
    parser.add_argument("--owner-token", default=os.getenv("WALLET_OWNER_TOKEN"))
    args = parser.parse_args()
    if not args.owner_token:
        print("set WALLET_OWNER_TOKEN or pass --owner-token", file=sys.stderr)
        return 2

    with httpx.Client(base_url=args.url, timeout=30) as client:
        health = client.get("/health").json()
        print(f"service: {health}")

        mandate = json.loads((CONFIG / "mandate.demo.json").read_text(encoding="utf-8"))
        activation = client.post(
            "/wallet/mandate/activate",
            json={"mandate_id": mandate["mandate_id"], "mandate": mandate},
            headers={"X-Owner-Token": args.owner_token},
        )
        if activation.status_code != 200:
            print(f"mandate activation failed: {activation.status_code} {activation.text}", file=sys.stderr)
            return 1
        print(f"mandate: {activation.json()}")

        current = client.get("/wallet/mandate").json()
        print(f"active mandate: {current['mandate_id']} hash {current['mandate_hash']}")

    payees = json.loads((CONFIG / "payees.json").read_text(encoding="utf-8"))
    print("\npayee registry (mock addresses; seed_demo replaces them when accounts exist):")
    for party_id, entry in payees.items():
        print(f"  {party_id:24s} {entry['name']:34s} {entry['address']}")
    print("\nlender liquidity is seeded at service start (mock). Run the demo next: scripts/demo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
