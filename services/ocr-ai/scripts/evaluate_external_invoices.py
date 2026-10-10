"""Evaluate OCR-local extraction against a pinned, licensed synthetic invoice set."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
import unicodedata
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
ROOT = SERVICE.parents[1]
sys.path[:0] = [str(SERVICE), str(ROOT)]

from app.config import Settings  # noqa: E402
from app.pipeline import extract  # noqa: E402

CORPUS = ROOT / "data/invoices/external/shopify_invoice_test_pack"
FIXTURES = CORPUS / "fixtures"
OUTPUT = SERVICE / "docs/EXTERNAL_INVOICE_EVALUATION.json"
DETECTOR = SERVICE / ".cache/paddlex/official_models/PP-OCRv5_mobile_det"
ENGLISH_RECOGNIZER = SERVICE / ".cache/paddlex/official_models/en_PP-OCRv5_mobile_rec"

HEADER_FIELDS = (
    ("supplier.name", "supplier_name", "text"),
    ("buyer.name", "billTo", "text"),
    ("document_number", "invoiceNumber", "text"),
    ("issue_date", "invoiceDate", "text"),
    ("currency", "currency", "text"),
    ("subtotal", "subtotal", "decimal"),
    ("tax_amount", "tax", "decimal"),
    ("amount", "total", "decimal"),
)
LINE_FIELDS = (
    ("sku", "supplierSku", "text"),
    ("description", "description", "text"),
    ("quantity", "quantity", "decimal"),
    ("unit", "unit", "text"),
    ("unit_price", "unitPrice", "decimal"),
    ("total", "lineTotal", "decimal"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def comparable(value, kind: str):
    if value is None:
        return None
    if kind == "decimal":
        return Decimal(str(value))
    return " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()


def public_value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def field_result(field, expected, kind: str) -> dict:
    actual = field.value
    return {
        "expected": public_value(expected),
        "observed": public_value(actual),
        "status": field.status,
        "match": field.status == "present" and comparable(actual, kind) == comparable(expected, kind),
    }


def truth_coverage(expected: dict) -> list[str]:
    """List expected concepts this service's current schema cannot represent."""
    unsupported = []
    for key in ("discount", "freight", "duty"):
        if Decimal(str(expected.get(key, 0))) != 0:
            unsupported.append(key)
    if expected.get("taxRate") is not None:
        unsupported.append("taxRate")
    for index, line in enumerate(expected.get("lines", [])):
        unsupported_line_fields = (
            "barcode",
            "discount",
            "tax",
            "pack",
            "deliveredQuantity",
            "freeOfChargeQuantity",
        )
        for key in unsupported_line_fields:
            if line.get(key) not in (None, "", 0, 0.0):
                unsupported.append(f"lines[{index}].{key}")
    return unsupported


def selected_inputs() -> list[tuple[Path, dict, str]]:
    inputs = []
    for fixture_dir in sorted(path for path in FIXTURES.iterdir() if path.is_dir()):
        expected = json.loads((fixture_dir / "expected.json").read_text())
        inputs.append((fixture_dir / "invoice.pdf", expected, "pdf"))
        # This image represents only page one, while expected.json labels the
        # complete two-page invoice. Do not score those incompatible units.
        if fixture_dir.name != "02-multipage":
            inputs.append((fixture_dir / "invoice.png", expected, "png"))
    return inputs


def main() -> None:
    if not DETECTOR.is_dir() or not ENGLISH_RECOGNIZER.is_dir():
        raise SystemExit(
            "Stage PP-OCRv5_mobile_det and en_PP-OCRv5_mobile_rec first; see services/ocr-ai/README.md."
        )

    os.environ["OCR_PADDLE_DET_DIR"] = str(DETECTOR)
    os.environ["OCR_PADDLE_REC_DIR"] = str(ENGLISH_RECOGNIZER)
    os.environ["OCR_PADDLE_REC_NAME"] = "en_PP-OCRv5_mobile_rec"
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(SERVICE / ".cache/paddlex")
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    settings = Settings.from_env()
    settings = Settings(
        fingerprint_key=settings.fingerprint_key,
        bank_key=settings.bank_key,
        state_path=settings.state_path,
        paddle_enabled=True,
        qwen_enabled=False,
        qwen_url=settings.qwen_url,
        qwen_model=settings.qwen_model,
        development_mode=settings.development_mode,
        allow_reset=settings.allow_reset,
    )

    source_note = (CORPUS / "SOURCE.md").read_text()
    source_revision = "bb2e531cfa504e6f7200243620121c523f9f7622"
    records = []
    for index, (path, expected, file_format) in enumerate(selected_inputs(), start=1):
        started = time.monotonic()
        base = {
            "fixture": path.parent.name,
            "file": str(path.relative_to(ROOT)),
            "format": file_format,
            "language": expected.get("language"),
            "sha256": sha256(path),
            "expected_sha256": sha256(path.parent / "expected.json"),
        }
        try:
            result = extract(path.read_bytes(), "invoice", settings)
            document = result.document
            expected_header = dict(expected)
            expected_header["supplier_name"] = expected["supplier"]["name"]
            observed_header = {}
            for field_name, truth_key, kind in HEADER_FIELDS:
                field = (
                    document.supplier.name
                    if field_name == "supplier.name"
                    else document.buyer.name
                    if field_name == "buyer.name"
                    else getattr(document, field_name)
                )
                observed_header[field_name] = field_result(field, expected_header[truth_key], kind)

            line_matches = []
            expected_lines = expected.get("lines", [])
            line_count_matches = len(document.lines) == len(expected_lines)
            for line_index, truth in enumerate(expected_lines):
                actual_line = document.lines[line_index] if line_count_matches else None
                cells = {}
                for actual_key, truth_key, kind in LINE_FIELDS:
                    actual_field = getattr(actual_line, actual_key) if actual_line else None
                    cells[actual_key] = (
                        field_result(actual_field, truth.get(truth_key), kind)
                        if actual_field
                        else {
                            "expected": public_value(truth.get(truth_key)),
                            "observed": None,
                            "status": "missing_or_unaligned",
                            "match": False,
                        }
                    )
                line_matches.append(cells)

            records.append(
                {
                    **base,
                    "status": "evaluated",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "engine": document.extractor,
                    "pages": len(result.document.evidence)
                    and max(reference.page for reference in result.document.evidence)
                    or 0,
                    "header_fields": observed_header,
                    "header_match_count": sum(item["match"] for item in observed_header.values()),
                    "header_field_count": len(observed_header),
                    "expected_line_count": len(expected_lines),
                    "observed_line_count": len(document.lines),
                    "line_count_match": line_count_matches,
                    "line_fields": line_matches,
                    "unsupported_expected_concepts": truth_coverage(expected),
                    "review_reasons": document.review_reasons,
                    "injection_flags": result.injection_flags,
                }
            )
        except Exception as exc:  # Keep a complete failure record without dumping source data.
            records.append(
                {
                    **base,
                    "status": "failed",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "error_type": type(exc).__name__,
                }
            )
        OUTPUT.write_text(json.dumps({"status": "running", "records": records}, indent=2) + "\n")
        current = records[-1]
        print(
            f"{index}/{len(selected_inputs())} {path.parent.name} {file_format}: "
            f"{current.get('header_match_count', 0)}/{current.get('header_field_count', 0)} headers, "
            f"{current.get('observed_line_count', 0)}/{current.get('expected_line_count', 0)} lines",
            flush=True,
        )

    groups = defaultdict(list)
    for record in records:
        groups[f"{record['language']}/{record['format']}"].append(record)
    summary = {
        key: {
            "documents": len(group),
            "evaluated": sum(item["status"] == "evaluated" for item in group),
            "failed": sum(item["status"] != "evaluated" for item in group),
            "header_matches": sum(item.get("header_match_count", 0) for item in group),
            "header_fields": sum(item.get("header_field_count", 0) for item in group),
            "documents_with_exact_lines": sum(
                item.get("line_count_match", False)
                and all(
                    all(field["match"] for field in line.values()) for line in item.get("line_fields", [])
                )
                for item in group
            ),
            "expected_lines": sum(item.get("expected_line_count", 0) for item in group),
            "observed_lines": sum(item.get("observed_line_count", 0) for item in group),
            "unsupported_concept_occurrences": sum(
                len(item.get("unsupported_expected_concepts", [])) for item in group
            ),
            "elapsed_seconds": round(sum(item.get("elapsed_seconds", 0) for item in group), 3),
        }
        for key, group in groups.items()
    }
    code_hashes = {
        str(path.relative_to(SERVICE)): sha256(path) for path in sorted((SERVICE / "app").rglob("*.py"))
    }
    code_hashes[str(Path(__file__).relative_to(SERVICE))] = sha256(Path(__file__))
    total_header_matches = sum(item.get("header_match_count", 0) for item in records)
    total_header_fields = sum(item.get("header_field_count", 0) for item in records)
    total_expected_lines = sum(item.get("expected_line_count", 0) for item in records)
    total_observed_lines = sum(item.get("observed_line_count", 0) for item in records)
    total_line_field_matches = sum(
        field["match"] for item in records for line in item.get("line_fields", []) for field in line.values()
    )
    total_line_fields = sum(len(line) for item in records for line in item.get("line_fields", []))
    report = {
        "status": "complete" if all(item["status"] == "evaluated" for item in records) else "partial",
        "data_origin": "external-publisher synthetic fixtures; no customer documents",
        "source": {
            "repository": "https://github.com/SalorWorks/shopify-invoice-test-pack",
            "revision": source_revision,
            "version": "1.0.0",
            "license": "CC-BY-4.0",
            "retrieved": "2026-10-10",
            "source_note_sha256": hashlib.sha256(source_note.encode()).hexdigest(),
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "paddleocr": package_version("paddleocr"),
            "paddlepaddle": package_version("paddlepaddle"),
            "paddle_recognizer": "en_PP-OCRv5_mobile_rec",
            "qwen_enabled": False,
            "evaluation_scope": (
                "OCR-local extract(); no HTTP compatibility, history, or fraud calibration claim"
            ),
        },
        "totals": {
            "header_field_matches": total_header_matches,
            "header_fields": total_header_fields,
            "header_match_rate": round(total_header_matches / total_header_fields, 4)
            if total_header_fields
            else None,
            "documents_with_all_header_fields": sum(
                item.get("header_match_count") == item.get("header_field_count") for item in records
            ),
            "line_field_matches": total_line_field_matches,
            "line_fields": total_line_fields,
            "expected_lines": total_expected_lines,
            "observed_lines": total_observed_lines,
            "elapsed_seconds": round(sum(item.get("elapsed_seconds", 0) for item in records), 3),
        },
        "evaluation_role": (
            "development challenge only after parser changes; publisher-authored synthetic labels, "
            "not an independent holdout or production accuracy estimate"
        ),
        "comparison_baseline": {
            "captured_in_commit": "6885189",
            "header_field_matches": 29,
            "header_fields": 232,
            "line_field_matches": 0,
            "line_fields": 330,
            "expected_lines": 66,
            "observed_lines": 0,
            "note": (
                "Original run used the then-current parser and a line evaluator that did not map "
                "publisher supplierSku or score line units. Current results use corrected labels."
            ),
        },
        "input_counts": {
            "pdfs": sum(item["format"] == "pdf" for item in records),
            "pngs": sum(item["format"] == "png" for item in records),
            "multipage_png_skipped": 1,
        },
        "summary": summary,
        "code_hashes": code_hashes,
        "limitations": [
            "Publisher-provided synthetic expected.json labels are not independent human annotations.",
            (
                "This is a small supplemental challenge set, not a representative vendor holdout "
                "or production accuracy estimate."
            ),
            (
                "The OCR-local schema preserves raw line units, but does not represent discounts, "
                "freight, duty, barcodes, pack conversions, or free quantities; those concepts "
                "are reported as unsupported, not scored as extraction failures. Shared schemas "
                "do not carry the OCR-local unit field."
            ),
            (
                "This run uses the English Paddle recognition model. Arabic and bilingual Arabic "
                "layouts remain outside validated support and should be expected to abstain or "
                "require review."
            ),
            (
                "The multi-page fixture's PNG contains only page one and was excluded from "
                "whole-invoice scoring; its complete PDF was evaluated."
            ),
            (
                "Direct extraction-stack evaluation bypasses HTTP required-field rejection, "
                "observation history, downstream policy/wallet behavior, and Qwen; it does not "
                "establish transaction safety or fraud precision/recall."
            ),
        ],
        "records": records,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "summary": summary}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
