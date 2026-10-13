"""Deterministic checks; no OCR/model certainty can override missing evidence."""

from datetime import datetime
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from app.config import FINANCIAL_DECIMAL_PRECISION, REVIEW_CONFIDENCE
from app.models import DocumentExtraction
from app.normalize import minor_unit, thai_tax_id_valid

CRITICAL_FIELDS = ("document_number", "issue_date", "due_date", "amount", "currency")


def validate_document(doc: DocumentExtraction) -> DocumentExtraction:
    with localcontext(prec=FINANCIAL_DECIMAL_PRECISION):
        return _validate_document(doc)


def _validate_document(doc: DocumentExtraction) -> DocumentExtraction:
    reasons = list(doc.review_reasons)
    if doc.document_type == "invoice" and doc.amount.value is not None and doc.amount.value <= 0:
        reasons.append("NON_POSITIVE_INVOICE_AMOUNT")
    required = (
        CRITICAL_FIELDS if doc.document_type == "invoice" else ("document_number", "currency", "amount")
    )
    for name in required:
        if getattr(doc, name).status != "present":
            reasons.append(f"MISSING_OR_UNRESOLVED:{name}")
    for party_name in ("supplier", "buyer"):
        party = getattr(doc, party_name)
        if party.name.status != "present":
            reasons.append(f"MISSING_OR_UNRESOLVED:{party_name}.name")
        if party.country.value == "TH" and party.identifier_scheme.value == "TAX_ID":
            identifier = party.legal_identifier.value
            if identifier and not thai_tax_id_valid(identifier):
                reasons.append(f"TAX_ID_INVALID:{party_name}")
                party.legal_identifier.confidence = 0
                party.legal_identifier.value = None
                party.legal_identifier.status = "unsupported"
    supplier_id, buyer_id = (
        (party.country.value, party.identifier_scheme.value, party.legal_identifier.value)
        for party in (doc.supplier, doc.buyer)
    )
    if supplier_id[2] and supplier_id == buyer_id:
        # A company cannot sell to itself; a receivable on such an invoice has no independent debtor.
        reasons.append("SUPPLIER_IS_BUYER")
    if doc.due_date.value and doc.issue_date.value and doc.due_date.value < doc.issue_date.value:
        reasons.append("DUE_BEFORE_ISSUE")
    if doc.issue_date.value and doc.issue_date.value > datetime.now(ZoneInfo("Asia/Bangkok")).date():
        reasons.append("ISSUE_IN_FUTURE")
    if not doc.lines:
        reasons.append("NO_LINE_EVIDENCE")
    for index, line in enumerate(doc.lines):
        if any(
            field.status != "present" or field.confidence < REVIEW_CONFIDENCE
            for field in (line.description, line.sku, line.quantity, line.unit_price, line.total)
        ):
            reasons.append(f"LINE_EVIDENCE_UNRESOLVED:{index}")
    if doc.currency.value:
        tolerance = minor_unit(doc.currency.value)

        def arithmetic(delta: Decimal, mismatch: str, scope: str) -> None:
            if abs(delta) > tolerance:
                reasons.append(mismatch)
            elif delta:
                reasons.append(f"ARITHMETIC_ROUNDING_REQUIRES_REVIEW:{scope}")

        for name in ("amount", "subtotal", "tax_amount"):
            field = getattr(doc, name)
            if field.value is not None and field.value % tolerance:
                reasons.append(f"MONEY_PRECISION:{name}")
        if "UNSUPPORTED_FINANCIAL_COMPONENT" not in reasons:
            for index, line in enumerate(doc.lines):
                if (
                    line.quantity.value is not None
                    and line.unit_price.value is not None
                    and line.total.value is not None
                ):
                    arithmetic(
                        line.quantity.value * line.unit_price.value - line.total.value,
                        f"LINE_MATH_MISMATCH:{index}",
                        f"line:{index}",
                    )
        if (
            doc.lines
            and doc.subtotal.value is not None
            and all(line.total.value is not None for line in doc.lines)
            and not any(
                reason.startswith(
                    ("LINE_LAYOUT_UNSUPPORTED", "LINE_EVIDENCE_UNRESOLVED", "UNREADABLE_PAGES_REQUIRE_OCR")
                )
                for reason in reasons
            )
            and "UNSUPPORTED_FINANCIAL_COMPONENT" not in reasons
        ):
            arithmetic(
                sum((line.total.value for line in doc.lines), Decimal(0)) - doc.subtotal.value,
                "LINE_SUM_MISMATCH",
                "subtotal",
            )
        if "UNSUPPORTED_FINANCIAL_COMPONENT" not in reasons and all(
            getattr(doc, name).value is not None for name in ("amount", "subtotal", "tax_amount")
        ):
            arithmetic(
                doc.subtotal.value + doc.tax_amount.value - doc.amount.value, "TOTAL_MISMATCH", "total"
            )
    for field in [*(getattr(doc, name) for name in required), doc.supplier.name, doc.buyer.name]:
        if field.status == "present" and field.confidence < REVIEW_CONFIDENCE:
            reasons.append("LOW_FIELD_CONFIDENCE")
    doc.review_reasons = list(dict.fromkeys(reasons))
    return doc
