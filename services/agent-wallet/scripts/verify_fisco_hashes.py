"""Check every FISCO transaction hash in a demo or deploy record against the chain (evidence, CLAUDE.md 11).

Runs where the FISCO SDK and the chain's certificates are available (the fisco-air container, see the README).
It asks the chain for each receipt and prints the block, status and revert reason, so the record can be
checked
without trusting the wallet's own output.

    python services/agent-wallet/scripts/verify_fisco_hashes.py \
        --sdk-dir /opt/python-sdk --config-dir /work/sdk --accounts-dir /work/accounts \
        --record services/agent-wallet/eval/demo_tx_hashes_fisco.md
"""

import argparse
import re
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]

from ledger.fisco import open_clients, revert_reason  # noqa: E402

HASH = re.compile(r"0x[0-9a-fA-F]{64}")


def as_int(value) -> int:
    return int(value, 16) if isinstance(value, str) and value.startswith("0x") else int(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk-dir", default="/opt/python-sdk")
    parser.add_argument("--config-dir", default="/work/sdk")
    parser.add_argument("--accounts-dir", default="/work/accounts")
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()

    hashes = sorted(set(HASH.findall(args.record.read_text(encoding="utf-8"))))
    client = open_clients(
        {"reader": str(Path(args.accounts_dir) / "deployer.pem")}, args.sdk_dir, args.config_dir
    )["reader"]
    print(f"{len(hashes)} hashes in {args.record.name}")
    missing = 0
    for tx_hash in hashes:
        receipt = client.getTransactionReceipt(tx_hash)
        if not isinstance(receipt, dict) or "blockNumber" not in receipt:
            missing += 1
            print(f"  {tx_hash}  NOT ON CHAIN")
            continue
        status = as_int(receipt.get("status", 0))
        reason = "" if status == 0 else (revert_reason(receipt.get("output")) or f"status {status}")
        print(
            f"  {tx_hash}  block {as_int(receipt['blockNumber']):>4}  "
            f"{'ok' if status == 0 else 'reverted'}  {reason}"
        )
    print(f"{len(hashes) - missing} of {len(hashes)} found on chain")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
