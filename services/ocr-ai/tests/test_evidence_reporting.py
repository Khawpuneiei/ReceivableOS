"""Reports cannot hide extraction failures or require the optional checked-in corpus."""

import json
import os
import sys
from types import SimpleNamespace

from scripts import consumer_review
from scripts import evaluate_external_invoices as external


def test_external_cli_failure_counts_against_accuracy_and_returns_nonzero(tmp_path, monkeypatch):
    expected = {
        "supplier": {"name": "Vendor"},
        "billTo": "Buyer",
        "invoiceNumber": "INV-1",
        "invoiceDate": "2026-10-01",
        "currency": "USD",
        "subtotal": "100",
        "tax": "0",
        "total": "100",
        "language": "en",
        "lines": [
            {
                "supplierSku": "A",
                "description": "Widget",
                "quantity": "1",
                "unit": "EA",
                "unitPrice": "100",
                "lineTotal": "100",
            }
        ],
    }
    inputs = []
    for name in ("readable", "unreadable"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "expected.json").write_text(json.dumps(expected))
        path = folder / "invoice.pdf"
        path.write_bytes(name.encode())
        inputs.append((path, expected, "pdf"))
    (tmp_path / "SOURCE.md").write_text("Unit-test source only")
    for attribute in ("ROOT", "CORPUS", "DETECTOR", "ENGLISH_RECOGNIZER"):
        monkeypatch.setattr(external, attribute, tmp_path)
    output = tmp_path / "report.json"
    monkeypatch.setattr(external, "OUTPUT", output)
    monkeypatch.setattr(external, "selected_inputs", lambda: inputs)
    for name in (
        "OCR_PADDLE_DET_DIR",
        "OCR_PADDLE_REC_DIR",
        "OCR_PADDLE_REC_NAME",
        "PADDLE_PDX_CACHE_HOME",
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK",
    ):
        monkeypatch.setenv(name, os.environ.get(name, ""))

    def field(value):
        return SimpleNamespace(value=value, status="present")

    def extract(content, *args):
        if content == b"unreadable":
            raise ValueError("private-diagnostic")
        header = {
            actual: field(expected[truth]) for actual, truth, _ in external.HEADER_FIELDS if "." not in actual
        }
        line = SimpleNamespace(
            **{actual: field(expected["lines"][0][truth]) for actual, truth, _ in external.LINE_FIELDS}
        )
        return SimpleNamespace(
            document=SimpleNamespace(
                **header,
                supplier=SimpleNamespace(name=field("Vendor")),
                buyer=SimpleNamespace(name=field("Buyer")),
                lines=[line],
                evidence=[],
                extractor="test-only",
                review_reasons=[],
            ),
            injection_flags=[],
        )

    monkeypatch.setattr(external, "extract", extract)
    assert external.main() == 1
    report = json.loads(output.read_text())
    assert report["status"] == "partial"
    assert report["totals"]["header_fields"] == 16
    assert report["totals"]["header_match_rate"] == 0.5
    assert report["totals"]["line_fields"] == 12
    assert report["totals"]["line_match_rate"] == 0.5
    assert report["totals"]["documents_with_all_header_fields"] == 1
    assert report["summary"]["en/pdf"]["failed"] == 1
    assert report["summary"]["en/pdf"]["header_fields"] == 16
    assert "private-diagnostic" not in output.read_text()


def test_empty_or_failed_sets_never_report_perfect_documents():
    assert external.summarize([])["header_match_rate"] is None
    totals = external.summarize([{"status": "failed", "header_field_count": 8, "expected_line_count": 2}])
    assert totals["header_match_rate"] == totals["line_match_rate"] == 0
    assert totals["documents_with_all_header_fields"] == 0


def test_consumer_report_runs_without_optional_corpus_or_hosted_upload(tmp_path, monkeypatch):
    output = tmp_path / "consumer.json"
    monkeypatch.setattr(sys, "argv", ["consumer_review.py", "--output", str(output)])
    for name in (
        "FINGERPRINT_HMAC_KEY",
        "BANK_TOKEN_HMAC_KEY",
        "OCR_PADDLE_ENABLED",
        "OCR_QWEN_ENABLED",
        "OCR_PADDLE_DET_DIR",
        "OCR_PADDLE_REC_NAME",
        "OCR_PADDLE_REC_DIR",
        "OCR_STATE_PATH",
    ):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    monkeypatch.setenv("OCR_HOSTED_VISION_ENABLED", "1")
    monkeypatch.setenv("LLM_API_KEY", "fake-key")
    monkeypatch.setattr(
        "app.llm_client.httpx.Client", lambda **kw: (_ for _ in ()).throw(AssertionError("cloud call"))
    )
    consumer_review.main()
    report = json.loads(output.read_text())
    assert report["models_enabled"] is False and report["data_origin"] == "synthetic-only"
    results = {row["case"]: row["response"] for row in report["records"]}
    assert len(results) == 5 and results["complete"]["status"] == "matched"
    assert results["missing_required"]["compatible_invoice"] is None
    assert results["mismatch"]["status"] == "mismatch"
    assert results["experimental_chinese"]["handoff"]["review_required"] is True
