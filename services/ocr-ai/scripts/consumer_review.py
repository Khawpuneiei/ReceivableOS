"""Prepare actual OCR-local API examples without changing or contacting consumers."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models import InvoicePoVerificationResult  # noqa: E402
from shared.schemas import ExtractedInvoice  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--language", choices=("en", "zh", "th"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = SERVICE.parents[1] / "data/invoices"
    cache = SERVICE / ".cache/paddlex/official_models"
    os.environ["FINGERPRINT_HMAC_KEY"] = secrets.token_hex(32)
    os.environ["BANK_TOKEN_HMAC_KEY"] = secrets.token_hex(32)
    os.environ["OCR_PADDLE_ENABLED"] = "1" if args.models else "0"
    os.environ["OCR_QWEN_ENABLED"] = "1" if args.models else "0"
    os.environ["OCR_PADDLE_DET_DIR"] = str(cache / "PP-OCRv5_mobile_det")
    cases = [
        ("complete", data / "en_invoice_clean.pdf", data / "en_po_clean.pdf", "th"),
        ("missing_required", data / "en_invoice_incomplete.pdf", data / "en_po_clean.pdf", "th"),
        ("mismatch", data / "en_invoice_amount_mismatch.pdf", data / "en_po_clean.pdf", "th"),
        (
            "international_scope",
            data / "reliability/invoice-en-stacked-0.pdf",
            data / "reliability/purchase_order-en-stacked-0.pdf",
            "en",
        ),
        (
            "experimental_chinese",
            data / "reliability/invoice-zh-stacked-0.pdf",
            data / "reliability/purchase_order-zh-stacked-0.pdf",
            "zh",
        ),
    ]
    if args.models:
        cases = [
            (
                f"{language}_scan_both_engines",
                data / f"reliability/invoice-{language}-stacked-1.png",
                data / f"reliability/purchase_order-{language}-stacked-1.png",
                language,
            )
            for language in ("en", "zh", "th")
            if args.language is None or args.language == language
        ]
    results = []
    with tempfile.TemporaryDirectory(prefix="ocr-consumer-review-") as temporary:
        with TestClient(app) as client:
            for case, invoice, po, language in cases:
                os.environ["OCR_STATE_PATH"] = str(Path(temporary) / f"{case}.sqlite")
                name = {
                    "en": "en_PP-OCRv5_mobile_rec",
                    "th": "th_PP-OCRv5_mobile_rec",
                    "zh": "PP-OCRv5_mobile_rec",
                }[language]
                os.environ["OCR_PADDLE_REC_NAME"], os.environ["OCR_PADDLE_REC_DIR"] = name, str(cache / name)
                started = time.monotonic()
                files = {
                    "invoice_file": (
                        invoice.name,
                        invoice.read_bytes(),
                        "image/png" if invoice.suffix == ".png" else "application/pdf",
                    ),
                    "po_file": (
                        po.name,
                        po.read_bytes(),
                        "image/png" if po.suffix == ".png" else "application/pdf",
                    ),
                }
                response = client.post("/ocr/verify", files=files, headers={"Idempotency-Key": case})
                response.raise_for_status()
                payload = response.json()
                InvoicePoVerificationResult.model_validate(payload)
                if payload["compatible_invoice"]:
                    ExtractedInvoice.model_validate(payload["compatible_invoice"])
                assert "100-200-3001" not in response.text and "1002003001" not in response.text
                results.append(
                    {
                        "case": case,
                        "http_status": response.status_code,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "response": payload,
                    }
                )
                print(
                    f"{case}: {payload['status']}; compatible={payload['compatible_invoice'] is not None}",
                    flush=True,
                )
    target = args.output or SERVICE / "docs" / (
        "GLOBAL_HTTP_SMOKE.json" if args.models else "CONSUMER_REVIEW_EXAMPLES.json"
    )
    target.write_text(
        json.dumps(
            {
                "source": "actual TestClient multipart API requests with isolated temporary state",
                "models_enabled": args.models,
                "data_origin": "synthetic-only",
                "records": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
