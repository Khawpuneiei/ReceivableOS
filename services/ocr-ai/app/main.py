"""ocr-ai: invoice OCR, OCR-injection flags and fraud score.

Stub: returns the shared demo invoice (docs/02-finance-domain.md section 10) for any file.
Replace the body of `extract` with the real pipeline; fingerprint rules are in this service's CLAUDE.md.
"""

import hashlib
import hmac
import logging
import os
from datetime import date
from decimal import Decimal

from fastapi import FastAPI, File, UploadFile

from shared.schemas import ExtractedInvoice, LineItem, Party

log = logging.getLogger("ocr-ai")
app = FastAPI(title="ocr-ai")

DEV_FINGERPRINT_KEY = "receivableos-dev-fingerprint-key"


def _fingerprint_key() -> bytes:
    key = os.getenv("FINGERPRINT_HMAC_KEY")
    if not key:
        log.warning("FINGERPRINT_HMAC_KEY is not set; using the fixed dev key")
        key = DEV_FINGERPRINT_KEY
    return key.encode()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ocr-ai"}


@app.post("/ocr/extract", response_model=ExtractedInvoice)
async def extract(file: UploadFile = File(...)) -> ExtractedInvoice:
    content = await file.read()
    digest = hashlib.sha256(content).hexdigest()
    issue_date = date(2026, 10, 1)
    # v1|supplier_key|buyer_key|norm(invoice_no)|amount:.2f|currency|issue_date
    canonical = f"v1|0105559000000|0107559000001|SFPINV2026142|749000.00|THB|{issue_date.isoformat()}"
    fingerprint = hmac.new(_fingerprint_key(), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return ExtractedInvoice(
        invoice_id=f"inv_{digest[:12]}",
        supplier=Party(name="Siam Fresh Pack Co., Ltd.", tax_id="0105559000000"),
        buyer=Party(name="Mekong Basket Retail PCL", tax_id="0107559000001"),
        invoice_no="SFP-INV-2026-0142",
        issue_date=issue_date,
        due_date=date(2026, 11, 15),
        amount=Decimal("749000.00"),
        currency="THB",
        line_items=[
            LineItem(
                description="Food trays",
                qty=Decimal("50000"),
                unit_price=Decimal("14.00"),
                total=Decimal("700000.00"),
            ),
            LineItem(description="VAT 7%", unit_price=Decimal("49000.00"), total=Decimal("49000.00")),
        ],
        confidence=0.5,
        injection_flags=[],
        fraud_score=0.0,
        fraud_flags=["stub"],
        doc_hash=f"sha256:{digest}",
        invoice_fingerprint=f"0x{fingerprint}",
    )
