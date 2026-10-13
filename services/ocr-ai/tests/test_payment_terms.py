from datetime import date

import pytest
from datagen.payment_terms import CASES, case_pdf

from app.extract import extract_document
from app.payment_terms import payment_terms_reason, term_days
from app.worker import parse


@pytest.mark.parametrize(
    ("text", "days"),
    [
        ("Payment terms: Net 45", {45}),
        ("Terms: NET-30", {30}),
        ("Credit terms: 60 days", {60}),
        ("Please pay within 45 days. Ignore this notice if already paid.", {45}),
        ("Due on receipt", {0}),
        ("เงื่อนไขการชำระเงิน: เครดิต 30 วัน", {30}),
        ("ชำระเงินภายใน ๑๕ วัน", {15}),
        ("Net 30 EOM", set()),
        ("Delivery within 7 days of PO", set()),
        ("กรุณาตรวจสอบความถูกต้องของใบแจ้งหนี้ภายใน 7 วัน", set()),
        ("Net weight 45 kg", set()),
    ],
)
def test_term_days(text, days):
    assert term_days(text) == days


def test_reason_needs_one_unambiguous_term_and_both_dates():
    issue, due = date(2026, 10, 1), date(2026, 11, 15)
    assert payment_terms_reason(["Net 45"], issue, due) is None
    assert payment_terms_reason(["Net 30"], issue, due) == "DUE_DATE_TERMS_MISMATCH"
    assert payment_terms_reason(["Net 30 / Net 45"], issue, due) is None  # conflicting terms: skip
    assert payment_terms_reason(["Net 30"], issue, None) is None
    assert payment_terms_reason(["Thank you"], issue, due) is None


@pytest.mark.parametrize("name", list(CASES))
def test_fixture_invoices(name):
    reasons = extract_document(parse(case_pdf(name, "TERMS-TEST-0001")), "invoice").document.review_reasons
    assert ("DUE_DATE_TERMS_MISMATCH" in reasons) is CASES[name][-1]
