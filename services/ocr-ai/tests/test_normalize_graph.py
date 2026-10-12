"""Jurisdiction, money, evidence integrity, and context-dependent graph rules."""

import secrets
from datetime import date
from decimal import Decimal

import pytest
from datagen.generate import document_lines, render_pdf
from pydantic import ValidationError

from app.extract import extract_document
from app.fingerprint import bank_token, entity_token, semantic_fingerprint
from app.fraud import graph_findings, score
from app.history import HistoryCapacityError, InvoiceObservation, ObservationStore
from app.models import ComparisonCheck, DocumentExtraction
from app.normalize import minor_unit, normalize_currency, normalize_date, normalize_number, thai_tax_id_valid
from app.worker import parse


@pytest.mark.parametrize(
    "text,locale,expected",
    [
        ("1,234.50", "en-US", "1234.50"),
        ("1.234,50", "de-DE", "1234.50"),
        ("๑๒๓๔.๕๐", "th-TH", "1234.50"),
        ("1000.125", None, "1000.125"),
    ],
)
def test_decimal_locale(text, locale, expected):
    assert normalize_number(text, locale) == Decimal(expected)


@pytest.mark.parametrize("text", ["1,234", "1.234", "NaN", "Infinity", "-1", "1,23.45"])
def test_ambiguous_or_invalid_money(text):
    with pytest.raises((ValueError, ArithmeticError)):
        normalize_number(text, None)


def test_minor_units_and_currency_evidence():
    assert minor_unit("JPY") == Decimal("1")
    assert minor_unit("KWD") == Decimal("0.001")
    assert minor_unit("THB") == Decimal("0.01")
    for raw in ["$", "XYZ", "XXX", "CNH", "XAU", "XDR"]:
        with pytest.raises(ValueError):
            normalize_currency(raw)


def test_dates():
    assert normalize_date("2026-10-01", None) == date(2026, 10, 1)
    assert normalize_date("01/10/2026", "en-GB") == date(2026, 10, 1)
    assert normalize_date("10/01/2026", "en-US") == date(2026, 10, 1)
    assert normalize_date("15/10/2026", None) == date(2026, 10, 15)
    with pytest.raises(ValueError):
        normalize_date("01/10/2026", None)
    with pytest.raises(ValueError):
        normalize_date("2026-02-30", None)


def test_legal_and_bank_scopes():
    key = secrets.token_hex(32)
    doc = extract_document(parse(render_pdf(document_lines())), "invoice").document
    assert thai_tax_id_valid("0105559000000")
    assert not thai_tax_id_valid("0105559000001")
    original = entity_token(doc.supplier, key)
    fingerprint = semantic_fingerprint(doc, key)
    doc.supplier.country.value = "DE"
    assert entity_token(doc.supplier, key) != original
    assert semantic_fingerprint(doc, key) != fingerprint
    doc.supplier.legal_identifier.status = "missing"
    doc.supplier.legal_identifier.value = None
    assert entity_token(doc.supplier, key) is None
    assert semantic_fingerprint(doc, key) is None
    bank = {"account": "ab 12-34", "country": "DE", "scheme": "IBAN"}
    assert bank_token(bank, key) == bank_token({**bank, "account": "AB1234"}, key)
    assert bank_token(bank, key) != bank_token({**bank, "country": "FR"}, key)
    assert bank_token(bank, key) != bank_token({**bank, "scheme": "LOCAL"}, key)


def observation(number, supplier, *, anomalies=None, amount="10.00", country="TH"):
    key = "ephemeral-test-only"
    token = bank_token(
        {"account": "fake-001", "country": country, "scheme": "LOCAL", "institution": "EXAMPLE-BANK"}, key
    )
    return InvoiceObservation(
        doc_hash="sha256:" + number.zfill(64),
        invoice_number=number,
        amount=Decimal(amount),
        currency="THB",
        issue_date=date(2026, 10, 1),
        supplier_token="entity:v1:" + supplier.zfill(64),
        buyer_token="entity:v1:" + "f" * 64,
        bank_token=token,
        evidence_refs=["ev:" + number.zfill(64)],
        anomaly_codes=anomalies or [],
    )


def test_shared_account_and_cluster_independent_evidence():
    records = [("a", observation("1", "a")), ("b", observation("2", "b"))]
    findings = graph_findings(records, "b")
    assert [f.code for f in findings] == ["shared_bank_token"]
    assert score(findings) == 0.15
    assert findings[0].path[0] == "b" and findings[0].path[-1] == "a"
    assert len(findings[0].path) == 5 and findings[0].evidence_refs
    records = [
        ("a", observation("1", "a", anomalies=["math_inconsistent"])),
        ("b", observation("2", "b", anomalies=["po_currency_mismatch"])),
    ]
    assert {"shared_bank_token", "suspicious_cluster"} == {f.code for f in graph_findings(records, "b")}
    records[1][1].anomaly_codes = ["math_inconsistent"]
    assert "suspicious_cluster" not in {f.code for f in graph_findings(records, "b")}
    records[1][1].bank_token = observation("3", "b", country="DE").bank_token
    assert not graph_findings(records, "b")


def test_names_alone_and_same_entity_do_not_trigger_shared_accounts():
    records = [("a", observation("1", "a")), ("b", observation("2", "a"))]
    assert not graph_findings(records, "b")
    records[1][1].supplier_token = None
    assert not graph_findings(records, "b")


def test_store_capacity_reset_and_retries(tmp_path):
    store = ObservationStore(tmp_path / "history.sqlite", max_observations=1)
    digest = "sha256:" + "a" * 64
    first = store.observe(observation("1", "a"), request_digest=digest, idempotency_key="retry")
    retry = store.observe(observation("1", "a"), request_digest=digest, idempotency_key="retry")
    assert first.observation_id == retry.observation_id and retry.replayed
    with pytest.raises(HistoryCapacityError):
        store.observe(observation("2", "b"), request_digest=digest)
    with pytest.raises(PermissionError):
        store.reset(development_mode=True, allow_reset=False)
    store.reset(development_mode=True, allow_reset=True)
    assert store.observations() == []


def test_unresolved_evidence_rejected():
    doc = extract_document(parse(render_pdf(document_lines())), "invoice").document
    payload = doc.model_dump()
    payload["amount"]["evidence_refs"] = ["ev:" + "f" * 64]
    with pytest.raises(ValidationError):
        DocumentExtraction.model_validate(payload)
    with pytest.raises(ValidationError):
        ComparisonCheck(field="amount", status="match", rule_code="AMOUNT", invoice_value="10", po_value="10")


def test_correlated_amount_codes_do_not_satisfy_cluster_independence():
    records = [
        ("a", observation("1", "a", anomalies=["math_inconsistent"])),
        ("b", observation("2", "b", anomalies=["po_amount_mismatch"])),
    ]
    assert [f.code for f in graph_findings(records, "b")] == ["shared_bank_token"]
