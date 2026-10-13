import secrets
from pathlib import Path

import pytest
from datagen.thai_qr import CASES, OTHER_TAX_ID, SUPPLIER_TAX_ID, case_pdf, emv_payload

from app.config import Settings
from app.extract import extract_document
from app.normalize import thai_tax_id_valid
from app.pipeline import extract_invoice
from app.promptpay import crc16, parse_thai_qr, qr_findings
from app.worker import parse

REPO = Path(__file__).resolve().parents[3]


def settings(tmp_path) -> Settings:
    return Settings(
        secrets.token_hex(32), secrets.token_hex(32), tmp_path / "s.sqlite", False, False, "", "", True, False
    )


def test_crc_matches_the_ccitt_false_check_value():
    assert crc16("123456789") == "29B1"


def test_fixture_tax_ids_are_valid_and_different():
    assert thai_tax_id_valid(SUPPLIER_TAX_ID) and thai_tax_id_valid(OTHER_TAX_ID)
    assert SUPPLIER_TAX_ID != OTHER_TAX_ID


@pytest.mark.parametrize(
    ("payload", "proxy_type"),
    [
        (emv_payload("tax_id", SUPPLIER_TAX_ID, "10.00"), "tax_id"),
        (emv_payload("bill", SUPPLIER_TAX_ID, "10.00"), "tax_id"),
        (emv_payload("mobile", "0066812345678", None), "mobile"),
    ],
)
def test_parses_promptpay_and_bill_payment(payload, proxy_type):
    qr = parse_thai_qr(payload)
    assert qr.crc_valid and qr.proxy_type == proxy_type


@pytest.mark.parametrize("payload", ["https://invoice.example/verify", "000201", "0002010102XX", "x" * 600])
def test_non_thai_or_malformed_payloads_are_ignored(payload):
    assert parse_thai_qr(payload) is None


@pytest.mark.parametrize("name", list(CASES))
def test_qr_cross_check_cases(name, tmp_path):
    _, expected = CASES[name]
    response = extract_invoice(case_pdf(name, "QR-TEST-0001"), settings(tmp_path), None)
    assert {flag for flag in response.fraud_flags if flag.startswith("qr_")} == expected
    # The QR never fills a field: the printed values stay the extraction result.
    assert str(response.amount) == "749000.00"
    assert response.supplier.tax_id == SUPPLIER_TAX_ID


def test_findings_never_echo_the_qr_payee_or_amount():
    parsed = parse(case_pdf("swapped_payee", "QR-TEST-0002"))
    doc = extract_document(parsed, "invoice").document
    for item in qr_findings(parsed.qr_payloads, doc):
        assert OTHER_TAX_ID not in item.model_dump_json()


def test_qr_swap_demo_file_is_flagged(tmp_path):
    content = (REPO / "data/invoices/demo/06_qr_swap.pdf").read_bytes()
    response = extract_invoice(content, settings(tmp_path), None)
    assert "qr_payee_mismatch" in response.fraud_flags
    assert response.fraud_score >= 0.30
