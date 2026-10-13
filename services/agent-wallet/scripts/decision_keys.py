"""Ed25519 keys for signed credit decisions (app/guard/signatures.py).

    python services/agent-wallet/scripts/decision_keys.py keygen --key-id policy-ai-1 --out signer.pem
    python services/agent-wallet/scripts/decision_keys.py sign --key signer.pem --key-id policy-ai-1 \\
        --decision-hash 0x... --fingerprint 0x...

keygen writes the private key (keep it in policy-ai's environment, never in git) and prints the
config/decision_signers.json entry with the public key. sign prints the X-Decision-Signature header value.
"""

import argparse
import json
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]

from Crypto.PublicKey import ECC  # noqa: E402

from app.guard.signatures import sign  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("keygen")
    gen.add_argument("--key-id", required=True)
    gen.add_argument("--out", type=Path, required=True)
    sig = sub.add_parser("sign")
    sig.add_argument("--key", type=Path, required=True)
    sig.add_argument("--key-id", required=True)
    sig.add_argument("--decision-hash", required=True)
    sig.add_argument("--fingerprint", required=True)
    args = parser.parse_args()
    if args.cmd == "keygen":
        key = ECC.generate(curve="ed25519")
        args.out.write_text(key.export_key(format="PEM"), encoding="utf-8")
        public = key.public_key().export_key(format="raw").hex()
        print(json.dumps({"signers": {args.key_id: public}}, indent=2))
        return 0
    print(sign(args.key.read_text(encoding="utf-8"), args.key_id, args.decision_hash, args.fingerprint))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
