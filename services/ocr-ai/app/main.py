"""Invoice extraction and OCR-local pair verification; no financial action authority."""

import sqlite3
from contextlib import contextmanager
from threading import BoundedSemaphore

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.ingest import read_upload
from app.models import InvoicePoVerificationResult
from app.pipeline import OcrExtractResponse, extract_invoice, verify

_slots = BoundedSemaphore(2)


@contextmanager
def processing_slot():
    if not _slots.acquire(blocking=False):
        raise HTTPException(429, "OCR processing capacity is busy; retry later")
    try:
        yield
    except ValueError as exc:
        raise HTTPException(422, "Document evidence could not be validated; review is required") from exc
    except sqlite3.Error as exc:
        raise HTTPException(503, "OCR observation history is unavailable") from exc
    finally:
        _slots.release()


app = FastAPI(title="ocr-ai")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ocr-ai"}


@app.post("/ocr/extract", response_model=OcrExtractResponse)
async def extract(
    file: UploadFile = File(...), idempotency_key: str | None = Header(None)
) -> OcrExtractResponse:
    with processing_slot():
        content = await read_upload(file)
        return await run_in_threadpool(extract_invoice, content, Settings.from_env(), idempotency_key)


@app.post("/ocr/verify", response_model=InvoicePoVerificationResult)
async def verify_pair(
    invoice_file: UploadFile = File(...),
    po_file: UploadFile = File(...),
    idempotency_key: str | None = Header(None),
) -> InvoicePoVerificationResult:
    with processing_slot():
        invoice_bytes = await read_upload(invoice_file)
        po_bytes = await read_upload(po_file)
        return await run_in_threadpool(verify, invoice_bytes, po_bytes, Settings.from_env(), idempotency_key)
