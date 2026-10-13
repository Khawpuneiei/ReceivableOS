"""Run the end-to-end demo against the orchestrator. Owner: PM.

Start all four services first (see README.md), then:
    python services/orchestrator/run_demo.py [path/to/invoice]
"""

import json
import os
import sys
from pathlib import Path

import httpx

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
DEFAULT_INVOICE = (
    Path(__file__).resolve().parents[2] / "data" / "invoices" / "demo" / "01_happy.pdf"
)  # ocr-ai reads PDFs


def main() -> int:
    invoice_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INVOICE
    with invoice_path.open("rb") as f, httpx.Client(timeout=120) as client:
        r = client.post(f"{ORCHESTRATOR_URL}/flow/run", files={"file": (invoice_path.name, f)})
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
