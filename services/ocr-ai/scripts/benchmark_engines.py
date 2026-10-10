"""Measure both local engines on labeled synthetic scans; never a real-world benchmark."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]

from app.config import Settings  # noqa: E402
from app.extract import extract_document  # noqa: E402
from app.ingest import run_worker  # noqa: E402
from app.qwen import read_candidates  # noqa: E402

DATA = SERVICE.parents[1] / "data" / "invoices"
FIELDS = ("document_number", "amount", "currency", "issue_date", "due_date", "supplier_name", "buyer_name")


def main() -> None:
    cache = SERVICE / ".cache" / "paddlex" / "official_models"
    os.environ.setdefault("OCR_PADDLE_DET_DIR", str(cache / "PP-OCRv5_mobile_det"))
    os.environ.setdefault("OCR_PADDLE_REC_DIR", str(cache / "th_PP-OCRv5_mobile_rec"))
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    settings = Settings.from_env()
    labels = [json.loads(line) for line in (DATA / "labels.jsonl").read_text().splitlines()]
    records = []
    for label in labels:
        if label["case"] != "scan":
            continue
        content = (DATA / label["file"]).read_bytes()
        parsed = run_worker("parse", content)
        for engine in ("paddle", "qwen"):
            started = time.monotonic()
            values, error = {}, None
            try:
                if engine == "paddle":
                    document = extract_document(
                        run_worker("paddle", content), label["document_type"]
                    ).document
                    values = {
                        field: str(getattr(document, field).value)
                        if getattr(document, field).value is not None
                        else None
                        for field in FIELDS
                        if field not in {"supplier_name", "buyer_name"}
                    }
                    values.update(
                        supplier_name=document.supplier.name.value, buyer_name=document.buyer.name.value
                    )
                else:
                    candidates = read_candidates(parsed.images, settings)
                    if candidates is None:
                        error = "LOCAL_MODEL_UNAVAILABLE_OR_INVALID_OUTPUT"
                    else:
                        values = candidates.model_dump()
            except Exception:
                error = "ENGINE_FAILED_OR_TIMED_OUT"
            matches = {field: values.get(field) == label["truth"][field] for field in FIELDS}
            record = {
                "file": label["file"],
                "language": label["language"],
                "document_type": label["document_type"],
                "engine": engine,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "error": error,
                "field_matches": matches,
                "correct": sum(matches.values()),
                "total": len(FIELDS),
            }
            records.append(record)
            print(json.dumps(record), flush=True)
    report = {
        "data_origin": "synthetic-only",
        "comparison_policy": "Exact scalar string matches for seven fields, including monetary formatting",
        "prompt_version": "grand-total-payable-v2",
        "schema_policy": "Every nullable field is required; extra properties forbidden",
        "paddle_models": ["PP-OCRv5_mobile_det", "th_PP-OCRv5_mobile_rec"],
        "qwen_model": settings.qwen_model,
        "records": records,
        "limitations": [
            "Four generated scans; no independent real-world layouts or customer documents",
            "Qwen outputs are candidates; exact matches do not establish grounding",
            "Paddle per-span confidence is not calibrated field accuracy",
            "Per-request isolated Paddle worker includes import/model initialization cost",
        ],
    }
    (SERVICE / "docs" / "ENGINE_BENCHMARK.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
