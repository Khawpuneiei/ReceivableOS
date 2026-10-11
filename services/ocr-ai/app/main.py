"""Invoice extraction and OCR-local pair verification; no financial action authority."""

import os
import secrets
import sqlite3
from contextlib import contextmanager
from threading import BoundedSemaphore

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.cache import JsonCache
from app.config import Settings
from app.ingest import read_upload, run_worker
from app.llm_client import configured, read_hosted_candidates
from app.models import InvoicePoVerificationResult
from app.pipeline import OcrExtractResponse, extract_invoice, verify
from app.qwen import read_candidates_with_status
from app.supporting import CaseManifest, verify_case

_slots = BoundedSemaphore(2)
_results = JsonCache(capacity=500, ttl=900, max_bytes=8 * 1024 * 1024)


def result_scope() -> str:
    # Results cannot leak across state/key contexts (including isolated test/eval databases).
    return os.getenv("OCR_STATE_PATH", "default") + "|" + os.getenv("OCR_RESULT_ACCESS_TOKEN", "")


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


@app.post("/ocr/cases/verify")
async def case_evidence(manifest: str = Form(...), files: list[UploadFile] = File(...)) -> dict:
    with processing_slot():
        if len(files) > 12 or len(manifest) > 16 * 1024:
            raise HTTPException(413, "Case exceeds the 12-document or manifest limit")
        parsed_manifest = CaseManifest.model_validate_json(manifest)
        uploads = []
        total_bytes = 0
        for file in files:
            content = await read_upload(file)
            total_bytes += len(content)
            if total_bytes > 20 * 1024 * 1024:
                raise HTTPException(413, "Case exceeds the 20 MiB combined upload limit")
            uploads.append((file.filename or "", content))
        return await run_in_threadpool(verify_case, parsed_manifest, uploads, Settings.from_env())


@app.get("/ocr/invoices/{invoice_id}", response_model=OcrExtractResponse)
def get_invoice(invoice_id: str, x_ocr_result_token: str | None = Header(None)) -> OcrExtractResponse:
    authorize_result_access(x_ocr_result_token)
    result = _results.get(result_scope() + "|" + invoice_id)
    if result is None:
        raise HTTPException(404, "Invoice result is absent or expired; results expire after 15 minutes")
    return OcrExtractResponse.model_validate(result)


def authorize_result_access(token: str | None):
    configured_token = os.getenv("OCR_RESULT_ACCESS_TOKEN", "")
    if not configured_token:
        raise HTTPException(503, "Invoice retrieval access token is not configured")
    if not token or not secrets.compare_digest(token.encode(), configured_token.encode()):
        raise HTTPException(401, "Invoice retrieval requires a valid access token")


def warm_candidates(content: bytes, settings: Settings) -> dict:
    parsed = run_worker("parse", content)
    checks = []
    if settings.qwen_enabled:
        candidates, status = read_candidates_with_status(parsed.images, settings)
        checks.append({"provider": "local_qwen", "cache": status, "valid_schema": candidates is not None})
    if configured():
        candidates, status = read_hosted_candidates(parsed.images)
        checks.append({"provider": "hosted", "cache": status, "valid_schema": candidates is not None})
    return {
        "doc_hash": parsed.doc_hash,
        "checks": checks,
        "cache_scope": "process_local",
        "expires_in_seconds": 900,
        "observation_written": False,
    }


@app.post("/ocr/llm/prewarm")
async def prewarm(file: UploadFile = File(...), x_ocr_result_token: str | None = Header(None)) -> dict:
    authorize_result_access(x_ocr_result_token)
    with processing_slot():
        content = await read_upload(file)
        return await run_in_threadpool(warm_candidates, content, Settings.from_env())


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ocr-ai"}


@app.post("/ocr/extract", response_model=OcrExtractResponse)
async def extract(
    file: UploadFile = File(...), idempotency_key: str | None = Header(None)
) -> OcrExtractResponse:
    with processing_slot():
        settings = Settings.from_env()
        content = await read_upload(file, allow_legacy_demo=settings.development_mode)
        result = await run_in_threadpool(extract_invoice, content, settings, idempotency_key)
        if os.getenv("OCR_RESULT_ACCESS_TOKEN"):
            _results.put(result_scope() + "|" + result.invoice_id, result.model_dump(mode="json"))
        return result


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
