"""Independent invoice/PO checks on declared currency and tax bases."""

from app.models import ComparisonCheck, DocumentExtraction, FieldValue
from app.normalize import minor_unit, normalize_reference


def compare_documents(invoice: DocumentExtraction, po: DocumentExtraction) -> list[ComparisonCheck]:
    checks = []

    def compare(
        field: str,
        left: FieldValue,
        right: FieldValue,
        code: str,
        *,
        normalize=lambda x: x,
        eligible: bool = True,
        numeric: bool = False,
    ) -> None:
        resolved = (
            eligible
            and left.status == right.status == "present"
            and min(left.confidence, right.confidence) >= 0.8
        )
        if resolved:
            a, b = normalize(left.value), normalize(right.value)
            same = abs(a - b) <= minor_unit(invoice.currency.value) if numeric else a == b
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
            numeric=True,
        )
    left_lines = {line.sku.value: line for line in invoice.lines if line.sku.value}
    right_lines = {line.sku.value: line for line in po.lines if line.sku.value}
    unique_lines = len(left_lines) == len(invoice.lines) and len(right_lines) == len(po.lines)
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
            compare(f"line_items.{sku}.description", left.description, right.description, "LINE_DESCRIPTION")
            compare(f"line_items.{sku}.quantity", left.quantity, right.quantity, "LINE_QUANTITY")
            compare(
                f"line_items.{sku}.unit_price",
                left.unit_price,
                right.unit_price,
                "LINE_UNIT_PRICE",
                eligible=same_currency,
                numeric=True,
            )
    partial = bool(
        left_lines
        and right_lines
        and any(
            sku in right_lines
            and left.quantity.value is not None
            and right_lines[sku].quantity.value is not None
            and left.quantity.value < right_lines[sku].quantity.value
            for sku, left in left_lines.items()
        )
    )
    if partial:
        # Uploads contain order terms, not a trusted allocation ledger. Do not infer remaining capacity.
        checks.append(
            ComparisonCheck(
                field="partial_invoicing", status="unknown", rule_code="PARTIAL_ALLOCATION_EVIDENCE_REQUIRED"
            )
        )
        for check in checks:
            if check.field in {"subtotal", "tax_amount", "amount"} or check.field.endswith(".quantity"):
                check.status = "unknown"
                check.rule_code = "PARTIAL_ALLOCATION_EVIDENCE_REQUIRED"
    return checks
