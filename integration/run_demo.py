"""End-to-end ReceivableOS demo: invoice -> ocr-ai -> policy-ai -> agent-wallet.

Owner: PM. Run the three services first (see README.md), then:
    python integration/run_demo.py [path/to/invoice]
"""

import json
import os
import sys
from pathlib import Path

import httpx

OCR_URL = os.getenv("OCR_URL", "http://localhost:8001")
POLICY_URL = os.getenv("POLICY_URL", "http://localhost:8002")
WALLET_URL = os.getenv("WALLET_URL", "http://localhost:8003")
SAMPLES = Path(__file__).parent / "samples"


def show(step: str, data: dict) -> None:
    print(f"\n== {step} ==")
    print(json.dumps(data, indent=2, default=str))


def main() -> int:
    invoice_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SAMPLES / "demo_invoice.txt"
    profiles = json.loads((SAMPLES / "profiles.json").read_text())

    with httpx.Client(timeout=60) as client:
        with invoice_path.open("rb") as f:
            r = client.post(f"{OCR_URL}/ocr/extract", files={"file": (invoice_path.name, f)})
        r.raise_for_status()
        invoice = r.json()
        show("1. OCR extract", invoice)

        r = client.post(
            f"{POLICY_URL}/policy/decide",
            json={"invoice": invoice, **profiles},
        )
        r.raise_for_status()
        decision = r.json()
        show("2. Policy decision", decision)

        r = client.post(
            f"{WALLET_URL}/wallet/execute",
            json={
                "decision": decision,
                "payee": profiles["supplier_profile"].get("wallet_address", "0xSUPPLIER"),
                "amount": decision["limit"],
                "currency": invoice["currency"],
                "invoice_id": invoice["invoice_id"],
            },
        )
        r.raise_for_status()
        show("3. Wallet execution", r.json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
