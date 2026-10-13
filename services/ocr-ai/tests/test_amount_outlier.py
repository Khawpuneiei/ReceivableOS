import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from datagen.amount_history import CASES
from scripts.amount_history_eval import run_case

from app.fraud import graph_findings, score
from app.history import InvoiceObservation


def observation(number: str, amount: str, *, buyer: str = "f", currency: str = "THB") -> InvoiceObservation:
    return InvoiceObservation(
        doc_hash="sha256:" + number.zfill(64),
        invoice_number=number,
        amount=Decimal(amount),
        currency=currency,
        issue_date=date(2026, 10, 1),
        supplier_token="entity:v1:" + "a" * 64,
        buyer_token="entity:v1:" + buyer * 64,
        evidence_refs=["ev:" + number.zfill(64)],
    )


def history(*amounts: str) -> list[tuple[str, InvoiceObservation]]:
    return [(f"o{index}", observation(str(index), amount)) for index, amount in enumerate(amounts)]


def codes(records, current_id):
    return [item.code for item in graph_findings(records, current_id)]


def test_three_times_the_pair_median_is_an_outlier():
    records = [*history("700000", "800000", "750000"), ("now", observation("9", "2250000"))]
    findings = graph_findings(records, "now")
    assert [item.code for item in findings] == ["amount_outlier"]
    assert score(findings) == 0.15  # review, never reject on its own
    assert findings[0].path[0] == "now" and findings[0].evidence_refs


@pytest.mark.parametrize(
    ("records", "why"),
    [
        ([*history("700000", "800000"), ("now", observation("9", "9000000"))], "only two prior invoices"),
        ([*history("700000", "800000", "750000"), ("now", observation("9", "2249999"))], "just under 3x"),
        (
            [*history("700000", "800000", "750000"), ("now", observation("9", "9000000", buyer="e"))],
            "different buyer has no history",
        ),
        (
            [*history("700000", "800000", "750000"), ("now", observation("9", "9000000", currency="USD"))],
            "different currency",
        ),
    ],
)
def test_no_outlier_without_enough_scoped_history(records, why):
    assert "amount_outlier" not in codes(records, "now"), why


@pytest.mark.parametrize("name", ["ordinary_next_month", "spike_3x", "spike_other_buyer_no_history"])
def test_pipeline_sequences(name):
    with tempfile.TemporaryDirectory() as folder:
        response = run_case(name, Path(folder))
    assert ("amount_outlier" in response.fraud_flags) is CASES[name][-1]
    assert response.fraud_score < 0.30
