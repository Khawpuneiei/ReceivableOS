import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from datagen.related_party import CASES, invoice
from scripts.related_party_eval import run_case

from app.extract import extract_document
from app.fraud import graph_findings, score
from app.history import InvoiceObservation
from app.validate import validate_document
from app.worker import parse

A, B = "entity:v1:" + "a" * 64, "entity:v1:" + "b" * 64


def observation(number, supplier, buyer, amount="749000", issued=date(2026, 10, 1), currency="THB"):
    return InvoiceObservation(
        doc_hash="sha256:" + number.zfill(64),
        invoice_number=number,
        amount=Decimal(amount),
        currency=currency,
        issue_date=issued,
        supplier_token=supplier,
        buyer_token=buyer,
        evidence_refs=["ev:" + number.zfill(64)],
    )


def codes(previous):
    return [item.code for item in graph_findings([("old", previous), ("now", observation("2", A, B))], "now")]


def test_round_trip_is_flagged_for_review_only():
    findings = graph_findings(
        [("old", observation("1", B, A, "740000", date(2026, 9, 15))), ("now", observation("2", A, B))], "now"
    )
    assert [item.code for item in findings] == ["circular_invoicing"]
    assert score(findings) == 0.15
    assert findings[0].path == ["now", "old"]


@pytest.mark.parametrize(
    ("previous", "why"),
    [
        (observation("1", B, A, "120000"), "reverse amount far from this one"),
        (observation("1", B, A, issued=date(2026, 5, 1)), "outside the 90-day window"),
        (observation("1", B, A, currency="USD"), "different currency"),
        (observation("1", A, B), "same direction"),
        (observation("1", B, "entity:v1:" + "c" * 64), "reverse to a different company"),
    ],
)
def test_no_round_trip(previous, why):
    assert "circular_invoicing" not in codes(previous), why


def _reasons(content: bytes) -> list[str]:
    return validate_document(extract_document(parse(content), "invoice").document).review_reasons


def test_supplier_billing_itself_needs_review():
    assert "SUPPLIER_IS_BUYER" in _reasons(invoice(50_000, "RP-TEST-0001", "2026-10-01", self_billed=True))
    assert "SUPPLIER_IS_BUYER" not in _reasons(invoice(50_000, "RP-TEST-0002", "2026-10-01"))


@pytest.mark.parametrize("name", ["round_trip", "reciprocal_small_purchase"])
def test_pipeline_sequences(name):
    with tempfile.TemporaryDirectory() as folder:
        response = run_case(name, Path(folder))
    assert ("circular_invoicing" in response.fraud_flags) is (CASES[name][-1] == "circular_invoicing")
    assert response.fraud_score < 0.30
