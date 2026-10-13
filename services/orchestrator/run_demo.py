"""Run the end-to-end demo against the orchestrator. Owner: PM.

Start all four services first (see README.md), then:
    python services/orchestrator/run_demo.py [path/to/invoice] [--no-repay]

Posts the invoice to /flow/run, prints every step, and when the draw executed posts "buyer paid" to
/flow/repay. The default invoice is the clean demo PDF; the attack PDFs sit next to it in data/invoices/demo/.
"""

import json
import os
import sys
from pathlib import Path

import httpx

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
DEFAULT_INVOICE = Path(__file__).resolve().parents[2] / "data" / "invoices" / "demo" / "01_happy.pdf"


def summary(steps: dict, repay: dict | None) -> str:
    """One line per step, so the demo numbers can be read without scrolling through the JSON."""
    ocr, policy, wallet = steps.get("ocr") or {}, steps.get("policy") or {}, steps.get("wallet") or {}
    lines = [
        f"invoice   {ocr.get('invoice_no')}  {ocr.get('amount')} {ocr.get('currency')}  "
        f"fraud {ocr.get('fraud_score')}  injection {ocr.get('injection_flags')}",
        f"registry  duplicate={steps.get('registry', {}).get('duplicate')}  "
        f"TX-1 {steps.get('register', {}).get('status')}",
    ]
    if policy:
        lines.append(
            f"policy    {policy.get('decision')}  advance {policy.get('advance_rate')}  "
            f"limit {policy.get('limit')}  fee/30d {policy.get('fee_rate')}  apr {policy.get('apr')}"
        )
    if wallet:
        lines.append(f"wallet    TX-4 {wallet.get('status')}  {wallet.get('chain_ref')}")
    if repay:
        lines.append(f"settle    TX-5 {repay.get('status')}  {repay.get('chain_ref')}")
    lines.append(f"outcome   {steps.get('outcome')}")
    return "\n".join(lines)


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--no-repay"]
    invoice_path = Path(args[0]) if args else DEFAULT_INVOICE
    with invoice_path.open("rb") as f, httpx.Client(timeout=120) as client:
        r = client.post(f"{ORCHESTRATOR_URL}/flow/run", files={"file": (invoice_path.name, f)})
        r.raise_for_status()
        steps = r.json()
        print(json.dumps(steps, indent=2))
        repay = None
        if "--no-repay" not in sys.argv and steps.get("wallet", {}).get("status") == "executed":
            r = client.post(f"{ORCHESTRATOR_URL}/flow/repay", data={"invoice_id": steps["ocr"]["invoice_id"]})
            r.raise_for_status()
            repay = r.json()
            print(json.dumps(repay, indent=2))
    print("\n" + summary(steps, repay))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
