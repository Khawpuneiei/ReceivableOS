"""External synthetic invoice layouts are exercised through the pair upload API."""

from pathlib import Path

from datagen.generate import render_pdf

from app.extract import extract_document
from app.validate import validate_document
from app.worker import parse

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "data/invoices/external/shopify_invoice_test_pack/fixtures/01-simple-english/invoice.pdf"
)
PO_FIXTURE = Path(__file__).resolve().parents[3] / "data/invoices/en_po_clean.pdf"


def test_simple_english_invoice_labels_and_six_column_table_are_extracted(client):
    content = FIXTURE.read_bytes()
    response = client.post(
        "/ocr/verify",
        files={
            "invoice_file": ("invoice.pdf", content, "application/pdf"),
            "po_file": ("po.pdf", PO_FIXTURE.read_bytes(), "application/pdf"),
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    invoice = result["invoice"]
    assert invoice["document_number"]["value"] == "INV-2026-001"
    assert invoice["issue_date"]["value"] == "2026-08-01"
    assert invoice["buyer"]["name"]["value"] == "Example Grocery Trading LLC, Dubai"
    assert invoice["currency"]["value"] == "AED"
    assert invoice["subtotal"]["value"] == "60.00"
    assert invoice["tax_amount"]["value"] == "3.00"
    assert invoice["amount"]["value"] == "63.00"
    assert len(invoice["lines"]) == 1
    line = invoice["lines"][0]
    assert line["sku"]["value"] == "SUP-WAT-330"
    assert line["description"]["value"] == "Sparkling Water 330ml"
    assert line["quantity"]["value"] == "24"
    assert line["unit"]["value"] == "EA"
    assert line["unit_price"]["value"] == "2.50"
    assert line["total"]["value"] == "60.00"

    # The letterhead is a useful candidate, but its business role still needs a reviewer.
    assert invoice["supplier"]["name"]["status"] == "ambiguous"
    assert invoice["supplier"]["name"]["value"] is None
    assert invoice["supplier"]["name"]["raw_value"] == "Fictional Gulf Foods LLC"
    assert "ROLE_INFERRED:supplier.name" in invoice["review_reasons"]

    evidence_ids = {item["ref_id"] for item in invoice["evidence"]}
    for field in (
        invoice["document_number"],
        invoice["issue_date"],
        invoice["buyer"]["name"],
        invoice["subtotal"],
        invoice["tax_amount"],
        invoice["amount"],
        line["unit"],
    ):
        assert field["evidence_refs"]
        assert set(field["evidence_refs"]) <= evidence_ids


def test_amount_with_a_currency_code_must_match_the_declared_invoice_currency():
    document = extract_document(
        parse(
            render_pdf(
                [
                    "Invoice: INV-CURRENCY-1",
                    "Date: 2026-08-01",
                    "Due Date: 2026-08-31",
                    "Supplier: Example Seller Ltd",
                    "Bill to: Example Buyer Ltd",
                    "Currency: AED",
                    "Subtotal AED 100.00",
                    "VAT 5% AED 5.00",
                    "Total EUR 105.00",
                    "Item: A | Widget | 1 | EA | 100.00 | 100.00",
                ]
            )
        ),
        "invoice",
    ).document

    assert document.amount.status == "ambiguous"
    assert document.amount.value is None
    assert "AMBIGUOUS:amount" in document.review_reasons
    assert "UNMODELED_TAX_RATE" in document.review_reasons


def test_unsupported_discount_requires_review_without_false_total_mismatch():
    document = validate_document(
        extract_document(
            parse(
                render_pdf(
                    [
                        "Invoice: INV-DISCOUNT-1",
                        "Date: 2026-08-01",
                        "Due Date: 2026-08-31",
                        "Supplier: Example Seller Ltd",
                        "Bill to: Example Buyer Ltd",
                        "Currency: AED",
                        "Subtotal: 100.00",
                        "Discount: 10.00",
                        "Tax: 0",
                        "Total: 90.00",
                        "Item: A | Widget | 1 | EA | 100.00 | 90.00",
                    ]
                )
            ),
            "invoice",
        ).document
    )

    assert "UNSUPPORTED_FINANCIAL_COMPONENT" in document.review_reasons
    assert "TOTAL_MISMATCH" not in document.review_reasons
    assert "LINE_MATH_MISMATCH:0" not in document.review_reasons


def test_unrecognized_commercial_table_is_named_as_unsupported():
    document = extract_document(
        parse(
            render_pdf(
                [
                    "SKU       DESCRIPTION       QTY       UOM       UNIT PRICE       "
                    "DISCOUNT       VAT       TOTAL",
                    "A         Widget            2         EA        10.00            "
                    "0.00            0.00      20.00",
                ]
            )
        ),
        "invoice",
    ).document

    assert document.lines == []
    assert "LINE_LAYOUT_UNSUPPORTED" in document.review_reasons
