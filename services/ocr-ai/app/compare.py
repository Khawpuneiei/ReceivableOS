"""Independent invoice/PO checks on declared currency and tax bases."""

import unicodedata
from decimal import Decimal

from app.config import REVIEW_CONFIDENCE
from app.models import ComparisonCheck, DocumentExtraction, FieldValue
from app.normalize import normalize_reference


def compare_documents(invoice: DocumentExtraction, po: DocumentExtraction) -> list[ComparisonCheck]:
    checks = []

    def normalize_unit(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()

    def compare(
        field: str,
        left: FieldValue,
        right: FieldValue,
        code: str,
        *,
        normalize=lambda x: x,
        eligible: bool = True,
    ) -> None:
        resolved = (
            eligible
            and left.status == right.status == "present"
            and min(left.confidence, right.confidence) >= REVIEW_CONFIDENCE
        )
        if resolved:
            a, b = normalize(left.value), normalize(right.value)
            # Printed amounts and commercial prices are facts, not rounding estimates.
            same = a == b
            status = "match" if same else "mismatch"
        else:
            status = "unknown"
        checks.append(
            ComparisonCheck(
                field=field,
                status=status,
                rule_code=code if resolved else f"{code}_UNKNOWN",
                invoice_value=str(left.value) if left.value is not None else None,
                po_value=str(right.value) if right.value is not None else None,
                invoice_evidence_refs=left.evidence_refs,
                po_evidence_refs=right.evidence_refs,
            )
        )

    compare(
        "po_reference",
        invoice.po_reference,
        po.document_number,
        "PO_REFERENCE",
        normalize=normalize_reference,
    )
    for party_name in ("supplier", "buyer"):
        left, right = getattr(invoice, party_name), getattr(po, party_name)
        scoped = (
            left.country.status == right.country.status == "present"
            and left.identifier_scheme.status == right.identifier_scheme.status == "present"
            and left.country.value == right.country.value
            and left.identifier_scheme.value == right.identifier_scheme.value
        )
        compare(
            f"{party_name}.identity",
            left.legal_identifier,
            right.legal_identifier,
            "PARTY_LEGAL_ID",
            eligible=scoped,
        )
        compare(f"{party_name}.country", left.country, right.country, "PARTY_COUNTRY")
        compare(
            f"{party_name}.identifier_scheme",
            left.identifier_scheme,
            right.identifier_scheme,
            "PARTY_ID_SCHEME",
        )
        compare(f"{party_name}.name", left.name, right.name, "PARTY_NAME_TEXT")
    compare("currency", invoice.currency, po.currency, "CURRENCY")
    same_currency = invoice.currency.value is not None and invoice.currency.value == po.currency.value
    compare("tax_basis", invoice.tax_basis, po.tax_basis, "TAX_BASIS")
    same_basis = invoice.tax_basis.value is not None and invoice.tax_basis.value == po.tax_basis.value
    for name in ("subtotal", "tax_amount", "amount"):
        compare(
            name,
            getattr(invoice, name),
            getattr(po, name),
            "AMOUNT_BASIS",
            eligible=same_currency and same_basis,
        )
    left_lines = {line.sku.value: line for line in invoice.lines if line.sku.value}
    right_lines = {line.sku.value: line for line in po.lines if line.sku.value}
    unique_lines = len(left_lines) == len(invoice.lines) and len(right_lines) == len(po.lines)
    comparable_units: set[str] = set()
    if not unique_lines or not left_lines or not right_lines:
        checks.append(
            ComparisonCheck(field="line_items", status="unknown", rule_code="LINE_EVIDENCE_UNKNOWN")
        )
    else:
        for sku in sorted(set(left_lines) | set(right_lines)):
            left, right = left_lines.get(sku), right_lines.get(sku)
            if left is None or right is None:
                available = left or right
                checks.append(
                    ComparisonCheck(
                        field=f"line_items.{sku}",
                        status="unknown",
                        rule_code="LINE_NOT_IN_BOTH_DOCUMENTS",
                        invoice_evidence_refs=available.sku.evidence_refs if left else [],
                        po_evidence_refs=available.sku.evidence_refs if right else [],
                    )
                )
                continue
            units_match = left.unit.status == right.unit.status == "present" and normalize_unit(
                left.unit.value
            ) == normalize_unit(right.unit.value)
            compare(
                f"line_items.{sku}.unit",
                left.unit,
                right.unit,
                "LINE_UNIT",
                normalize=normalize_unit,
            )
            if units_match:
                comparable_units.add(sku)
            compare(f"line_items.{sku}.description", left.description, right.description, "LINE_DESCRIPTION")
            compare(
                f"line_items.{sku}.quantity",
                left.quantity,
                right.quantity,
                "LINE_QUANTITY",
                eligible=sku in comparable_units,
            )
            compare(
                f"line_items.{sku}.unit_price",
                left.unit_price,
                right.unit_price,
                "LINE_UNIT_PRICE",
                eligible=same_currency and same_basis and sku in comparable_units,
            )
    partial_skus = {
        sku
        for sku, left in left_lines.items()
        if unique_lines
        and sku in right_lines
        and sku in comparable_units
        and left.quantity.status == right_lines[sku].quantity.status == "present"
        and min(left.quantity.confidence, right_lines[sku].quantity.confidence) >= REVIEW_CONFIDENCE
        and left.quantity.value < right_lines[sku].quantity.value
    }
    if partial_skus:
        # Uploads contain order terms, not a trusted allocation ledger. Do not infer remaining capacity.
        checks.append(
            ComparisonCheck(
                field="partial_invoicing", status="unknown", rule_code="PARTIAL_ALLOCATION_EVIDENCE_REQUIRED"
            )
        )
        for check in checks:
            partial_quantity = check.field in {f"line_items.{sku}.quantity" for sku in partial_skus}
            partial_amount = (
                check.field in {"subtotal", "tax_amount", "amount"}
                and check.status != "unknown"
                and Decimal(check.invoice_value) <= Decimal(check.po_value)
            )
            # Lower quantities need allocation evidence; proven over-order terms stay mismatches.
            if partial_quantity or partial_amount:
                check.status = "unknown"
                check.rule_code = "PARTIAL_ALLOCATION_EVIDENCE_REQUIRED"
    return checks
