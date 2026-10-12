"""Replay the checked-in four demo files in order, keeping history without sharing live state."""

import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

SERVICE = Path(__file__).resolve().parents[1]
REPO = SERVICE.parents[1]
sys.path[:0] = [str(SERVICE), str(REPO)]
from app.main import app  # noqa: E402


def main():
    records = []
    with tempfile.TemporaryDirectory(prefix="ocr-demo-order-") as temporary:
        env = {
            "OCR_STATE_PATH": str(Path(temporary) / "state.sqlite"),
            "LLM_API_KEY": "",
            "OCR_PADDLE_ENABLED": "0",
            "OCR_QWEN_ENABLED": "0",
            "FINGERPRINT_HMAC_KEY": secrets.token_hex(32),
            "BANK_TOKEN_HMAC_KEY": secrets.token_hex(32),
        }
        with patch.dict(os.environ, env), TestClient(app) as client:
            for file, expected in zip(
                sorted((REPO / "data/invoices/demo").glob("0[1-4]_*.pdf")),
                ("approve", "review", "reject", "reject"),
                strict=True,
            ):
                response = client.post(
                    "/ocr/extract", files={"file": (file.name, file.read_bytes(), "application/pdf")}
                )
                response.raise_for_status()
                invoice = response.json()
                gate = (
                    "reject"
                    if invoice["fraud_score"] >= 0.30
                    else (
                        "review" if invoice["injection_flags"] or invoice["confidence"] < 0.80 else "approve"
                    )
                )
                records.append(
                    {
                        "file": file.name,
                        "invoice_no": invoice["invoice_no"],
                        "fraud_score": invoice["fraud_score"],
                        "fraud_flags": invoice["fraud_flags"],
                        "injection_flags": invoice["injection_flags"],
                        "expected_policy": expected,
                        "evidence_gate": gate,
                        "passed": gate == expected,
                    }
                )
    report = {
        "data_origin": "synthetic-only",
        "ordered_results": records,
        "passed": all(row["passed"] for row in records),
        "policy_endpoint_called": False,
        "limitation": (
            "Evidence gate only; actual Policy guards are evaluated separately in DEMO_LOOP_RESULTS.json"
        ),
    }
    target = SERVICE / "docs/DEMO_ORDER_CHECK.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
