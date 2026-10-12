"""Automated supporting-document scenarios through multipart HTTP, isolated history each time."""

import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from datagen.financing_case import generate, supporting_pdf  # noqa: E402

from app.main import app  # noqa: E402


def evaluate(output: Path | None = None):
    cases = [
        ("complete_linked_case", None, None, "SUPPORTING_DOCUMENT_AUTHENTICITY_UNKNOWN"),
        (
            "receipt_shortage",
            "goods_receipt",
            {"Received Quantity": "49000"},
            "goods_receipt:SUPPORTING_QUANTITY_MISMATCH",
        ),
        (
            "unrelated_credit",
            "credit_note",
            {"Invoice Reference": "UNRELATED"},
            "credit_note:SUPPORTING_REFERENCE_MISMATCH:Invoice Reference",
        ),
        (
            "buyer_dispute",
            "buyer_confirmation",
            {"Acceptance Status": "disputed"},
            "BUYER_ACCEPTANCE_UNKNOWN_OR_DISPUTED",
        ),
        ("over_credit", "credit_note", {"Credit Amount": "800000"}, "DECLARED_ADJUSTMENTS_EXCEED_INVOICE"),
        ("missing_confirmation", "omit", None, "MISSING_DOCUMENT:buyer_confirmation"),
    ]
    results = []
    with tempfile.TemporaryDirectory(prefix="ocr-case-loop-") as temporary:
        root = Path(temporary)
        manifest = generate(root / "documents")
        for index, (name, kind, override, expected) in enumerate(cases):
            entries, files = [], []
            for entry in manifest["documents"]:
                if kind == "omit" and entry["document_type"] == "buyer_confirmation":
                    continue
                content = (root / "documents" / entry["filename"]).read_bytes()
                if kind == entry["document_type"]:
                    content = supporting_pdf(kind, overrides=override)
                entries.append(entry)
                files.append(("files", (entry["filename"], content, "application/pdf")))
            env = {
                "FINGERPRINT_HMAC_KEY": secrets.token_hex(32),
                "BANK_TOKEN_HMAC_KEY": secrets.token_hex(32),
                "OCR_STATE_PATH": str(root / f"state-{index}.sqlite"),
                "LLM_API_KEY": "",
                "OCR_PADDLE_ENABLED": "0",
                "OCR_QWEN_ENABLED": "0",
            }
            with patch.dict(os.environ, env), TestClient(app) as client:
                response = client.post(
                    "/ocr/cases/verify",
                    data={"manifest": json.dumps({**manifest, "documents": entries})},
                    files=files,
                )
            response.raise_for_status()
            body = response.json()
            passed = (
                expected in body["review_reasons"]
                and body["review_required"]
                and not body["financing_authority"]
            )
            if name == "complete_linked_case":
                passed = (
                    passed
                    and body["review_reasons"] == [expected]
                    and all(c["status"] == "match" for c in body["checks"])
                )
            if name == "unrelated_credit":
                passed = passed and body["declared_balance"]["credit_amount"] == "0"
            results.append(
                {
                    "case": name,
                    "passed": passed,
                    "http_status": response.status_code,
                    "uploaded_documents": len(entries),
                    "invoice_po_status": body["invoice_po"]["status"],
                    "checks": body["checks"],
                    "review_reasons": body["review_reasons"],
                    "declared_balance": body["declared_balance"],
                    "financing_authority": False,
                }
            )
    report = {
        "data_origin": "synthetic-only",
        "scenarios_passed": sum(row["passed"] for row in results),
        "scenarios_total": len(results),
        "results": results,
        "limitations": [
            "English labelled PDF support only; no issuer, bank, delivery or signature authentication",
            "Displayed balances are document claims, not an allocation or payment ledger",
        ],
    }
    target = output or SERVICE / "docs/CASE_LOOP_RESULTS.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["scenarios_passed"], "total": len(results), "report": str(target)}))
    return report


if __name__ == "__main__":
    result = evaluate()
    raise SystemExit(0 if result["scenarios_passed"] == result["scenarios_total"] else 1)
