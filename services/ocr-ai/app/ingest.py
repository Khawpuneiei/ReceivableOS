"""Bounded uploads and isolated, time-limited parser/OCR workers."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from typing import Literal

from fastapi import HTTPException, UploadFile
from pydantic import Field

from app.config import MAX_UPLOAD_BYTES, OCR_TIMEOUT_SECONDS, PARSER_TIMEOUT_SECONDS, SERVICE_DIR
from app.models import Digest, LocalModel


class Span(LocalModel):
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    confidence: float = Field(ge=0, le=1)
    source: Literal["pdf_text", "image_ocr"]
    ordinal: int
    size: float | None = None
    color: int | None = None
    hidden: bool = False


class ParsedDocument(LocalModel):
    doc_hash: Digest
    spans: list[Span]
    images: list[str]  # Private base64 PNGs; never returned in the public evidence contract.
    metadata_text: list[str] = Field(default_factory=list)
    engine: str


async def read_upload(upload: UploadFile) -> bytes:
    content = bytearray()
    try:
        while chunk := await upload.read(min(64 * 1024, MAX_UPLOAD_BYTES + 1 - len(content))):
            content.extend(chunk)
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "Upload exceeds the 10 MB limit")
    finally:
        await upload.close()
    data = bytes(content)
    detected = detect_format(data)
    allowed = {"pdf": {"application/pdf"}, "png": {"image/png"}, "jpeg": {"image/jpeg"}}
    if detected is None or upload.content_type not in allowed[detected]:
        raise HTTPException(415, "Only signature-verified PDF, JPEG, and PNG uploads are supported")
    return data


def detect_format(content: bytes) -> Literal["pdf", "png", "jpeg"] | None:
    if content.startswith(b"%PDF-"):
        return "pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return None


def digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def run_worker(mode: Literal["parse", "paddle"], content: bytes) -> ParsedDocument:
    # Parser/OCR children do not need application secrets or cloud credentials.
    allowed = {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "DYLD_LIBRARY_PATH",
        "OCR_PADDLE_DET_DIR",
        "OCR_PADDLE_REC_DIR",
        "OCR_PADDLE_REC_NAME",
        "PADDLE_PDX_CACHE_HOME",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    env["PYTHONPATH"] = os.pathsep.join([str(SERVICE_DIR), str(SERVICE_DIR.parents[1])])
    try:
        process = subprocess.run(
            [sys.executable, "-m", "app.worker", mode],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=SERVICE_DIR,
            timeout=PARSER_TIMEOUT_SECONDS if mode == "parse" else OCR_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(422, "Document processing timed out; review is required") from exc
    if process.returncode == 13:
        raise HTTPException(413, "Document exceeds the page, pixel, or text limit")
    if process.returncode != 0:
        raise HTTPException(422, "Document is unreadable or the configured OCR engine is unavailable")
    try:
        result = ParsedDocument.model_validate_json(process.stdout)
    except ValueError as exc:
        raise HTTPException(422, "Document processing returned invalid evidence") from exc
    if result.doc_hash != digest(content):
        raise HTTPException(422, "Document evidence digest does not match the upload")
    return result
