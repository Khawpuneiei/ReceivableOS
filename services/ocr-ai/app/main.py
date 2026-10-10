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
    # canonical content: supplier tax id | buyer tax id | invoice no | amount | currency | issue date
    canonical = f"0105559000000|0107559000001|SFP-2026-0101|749000.00|THB|{today.isoformat()}"
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    return ExtractedInvoice(
        invoice_id=f"inv_{digest[:12]}",
        supplier=Party(name="Siam Fresh Pack Co., Ltd.", tax_id="0105559000000"),
        buyer=Party(name="Mekong Basket Retail PCL", tax_id="0107559000001"),
        invoice_no="SFP-2026-0101",
        issue_date=today,
        due_date=today + timedelta(days=45),
        amount=Decimal("749000.00"),
        currency="THB",
        line_items=[],
        confidence=0.5,
        injection_flags=[],
        fraud_score=0.0,
        fraud_flags=["stub"],
        doc_hash=f"sha256:{digest}",
        invoice_fingerprint=f"sha256:{fingerprint}",
    )
