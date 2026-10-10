"""ocr-ai: invoice OCR, OCR-injection flags and fraud score.

Stub: returns a fixed invoice that matches the shared contract.
Replace the body of `extract` with the real pipeline.
"""

import hashlib
from datetime import date, timedelta
from decimal import Decimal

from fastapi import FastAPI, File, UploadFile

from shared.schemas import ExtractedInvoice, Party

app = FastAPI(title="ocr-ai")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ocr-ai"}


@app.post("/ocr/extract", response_model=ExtractedInvoice)
async def extract(file: UploadFile = File(...)) -> ExtractedInvoice:
    content = await file.read()
    digest = hashlib.sha256(content).hexdigest()
    today = date.today()
    return ExtractedInvoice(
        invoice_id=f"inv_{digest[:12]}",
        supplier=Party(name="Demo Supplier Co., Ltd."),
        buyer=Party(name="Demo Buyer Plc."),
        invoice_no="INV-0001",
        issue_date=today,
        due_date=today + timedelta(days=60),
        amount=Decimal("10000.00"),
        currency="USD",
        line_items=[],
        confidence=0.5,
        injection_flags=[],
        fraud_score=0.0,
        fraud_flags=["stub"],
        doc_hash=f"sha256:{digest}",
    )
