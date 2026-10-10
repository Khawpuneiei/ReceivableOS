"""Financial boundary cases through independently rendered invoice and PO uploads."""

from decimal import Decimal, localcontext

import pytest
from datagen.generate import document_lines, render_pdf

from app.compare import compare_documents
from app.extract import extract_document
from app.fingerprint import semantic_fingerprint
from app.models import InvoicePoVerificationResult
from app.normalize import normalize_number
from app.validate import validate_document
from app.worker import parse


def financial_lines(*, po=False, currency="THB", amount="100.00", items=None):
    lines = document_lines(po=po, currency=currency)
    lines = [line for line in lines if not line.startswith(("Item:", "Subtotal:", "Tax:", "Total:"))]
    return [
        *lines,
        f"Subtotal: {amount}",
        "Tax: 0",
        f"Total: {amount}",
        *(items or ["Item: A | Widget | 1 | 100 | 100"]),
    ]


def post_pair(client, invoice, po):
    response = client.post(
        "/ocr/verify",
        files={
            "invoice_file": ("invoice.pdf", render_pdf(invoice), "application/pdf"),
            "po_file": ("po.pdf", render_pdf(po), "application/pdf"),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("currency,delta", [("USD", "0.01"), ("JPY", "1"), ("KWD", "0.001")])
def test_printed_po_amount_difference_is_not_silently_matched(currency, delta):
    invoice = extract_document(parse(render_pdf(financial_lines(currency=currency))), "invoice").document
    po = extract_document(
        parse(
            render_pdf(
                financial_lines(po=True, currency=currency, amount=str(Decimal("100") + Decimal(delta)))
            )
        ),
        "purchase_order",
    ).document
    check = next(item for item in compare_documents(invoice, po) if item.field == "amount")
    assert check.status == "mismatch"


def test_equal_header_totals_do_not_hide_offsetting_unit_price_mismatches(client):
    invoice = financial_lines(items=["Item: A | Widget A | 2 | 10 | 20", "Item: B | Widget B | 2 | 40 | 80"])
    po = financial_lines(
        po=True, items=["Item: A | Widget A | 2 | 11 | 22", "Item: B | Widget B | 2 | 39 | 78"]
    )
    result = post_pair(client, invoice, po)
    assert result["status"] == "mismatch"
    assert result["handoff"]["review_required"] is True
    assert "PAIR_MISMATCH_REQUIRES_REVIEW" in result["review_reasons"]
    assert result["compatible_invoice"]["confidence"] < 0.8


def test_partial_line_does_not_hide_another_line_exceeding_the_po(client):
    invoice = financial_lines(items=["Item: A | Widget A | 5 | 10 | 50", "Item: B | Widget B | 5 | 10 | 50"])
    po = financial_lines(
        po=True, items=["Item: A | Widget A | 4 | 10 | 40", "Item: B | Widget B | 6 | 10 | 60"]
    )
    result = post_pair(client, invoice, po)
    quantities = {
        check["field"]: check["status"] for check in result["checks"] if check["field"].endswith(".quantity")
    }
    assert quantities["line_items.A.quantity"] == "mismatch"
    assert quantities["line_items.B.quantity"] == "unknown"
    assert result["status"] == "mismatch"


def test_zero_face_value_cannot_leave_extraction_without_review(client):
    response = client.post(
        "/ocr/extract",
        files={
            "file": (
                "zero.pdf",
                render_pdf(financial_lines(amount="0", items=["Item: A | Free sample | 1 | 0 | 0"])),
                "application/pdf",
            ),
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["review_required"] and result["handoff"]["review_required"]
    assert "NON_POSITIVE_INVOICE_AMOUNT" in result["validation_flags"]
    assert result["confidence"] < 0.8


def test_partial_quantity_cannot_hide_a_payable_above_the_full_order(client):
    result = post_pair(
        client,
        financial_lines(amount="12", items=["Item: A | Widget | 3 | 4 | 12"]),
        financial_lines(po=True, amount="4", items=["Item: A | Widget | 4 | 1 | 4"]),
    )
    amount = next(check for check in result["checks"] if check["field"] == "amount")
    assert amount["status"] == "mismatch"
    assert "po_amount_mismatch" in result["handoff"]["fraud_codes"]


def test_oversized_financial_number_returns_unresolved_instead_of_server_error(client):
    amount = "1234567890123456789012345678901234567890.00"
    response = client.post(
        "/ocr/extract",
        files={
            "file": (
                "large.pdf",
                render_pdf(
                    financial_lines(amount=amount, items=[f"Item: A | Widget | 1 | {amount} | {amount}"])
                ),
                "application/pdf",
            ),
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("raw", ["1E+100000", "0.0000000000001", "9" * 29])
def test_numeric_resource_limits_leave_extreme_observations_unresolved(raw):
    with pytest.raises(ValueError):
        normalize_number(raw, "en-US")


def test_semantic_identity_and_validation_are_independent_of_decimal_context():
    amount = "12345678.90"
    document = extract_document(
        parse(
            render_pdf(financial_lines(amount=amount, items=[f"Item: A | Widget | 1 | {amount} | {amount}"]))
        ),
        "invoice",
    ).document
    with localcontext() as context:
        context.prec = 64
        expected = semantic_fingerprint(document, "test-only-key")
        expected_reasons = validate_document(document.model_copy(deep=True)).review_reasons
    with localcontext() as context:
        context.prec = 6
        assert semantic_fingerprint(document, "test-only-key") == expected
        assert validate_document(document.model_copy(deep=True)).review_reasons == expected_reasons


@pytest.mark.parametrize("mutation", ["review", "confidence", "hash", "observation", "status"])
def test_pair_response_rejects_inconsistent_consumer_handoff(client, mutation):
    result = post_pair(
        client,
        financial_lines(items=["Item: A | Different description | 1 | 100 | 100"]),
        financial_lines(po=True),
    )
    assert result["status"] == "mismatch"
    if mutation == "review":
        result["handoff"]["review_required"] = False
    elif mutation == "confidence":
        result["compatible_invoice"]["confidence"] = 0.97
    elif mutation == "hash":
        result["handoff"]["document_hashes"] = ["sha256:" + "0" * 64, "sha256:" + "0" * 64]
    elif mutation == "observation":
        result["handoff"]["observation_id"] = "unbound-observation"
    else:
        result["status"] = "review"
    with pytest.raises(ValueError):
        InvoicePoVerificationResult.model_validate(result)


def test_minor_unit_internal_rounding_requires_review_without_fraud_claim(client):
    response = client.post(
        "/ocr/extract",
        files={
            "file": (
                "rounding.pdf",
                render_pdf(
                    financial_lines(
                        currency="USD", amount="99.99", items=["Item: A | Widget | 1 | 100 | 99.99"]
                    )
                ),
                "application/pdf",
            ),
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["review_required"]
    assert "ARITHMETIC_ROUNDING_REQUIRES_REVIEW:line:0" in result["validation_flags"]
    assert "math_inconsistent" not in result["fraud_flags"]
