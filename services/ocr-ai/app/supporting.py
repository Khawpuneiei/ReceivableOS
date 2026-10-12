"""English labelled supporting evidence, linked to invoice/PO; no authenticity authority."""

from decimal import Decimal, localcontext
from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from app.config import FINANCIAL_DECIMAL_PRECISION, Settings
from app.extract import INSTRUCTION, extract_document, reference_id
from app.ingest import digest, run_worker
from app.layout import anchored_rows, compact
from app.models import LocalModel
from app.normalize import normalize_date, normalize_number, normalize_reference
from app.pipeline import verify

SUPPORT_FIELDS = {
    "delivery_note": {"Shipped Quantity": "quantity", "Unit": "unit"},
    "goods_receipt": {"Received Quantity": "quantity", "Unit": "unit", "Receipt Date": "date"},
    "buyer_confirmation": {
        "Accepted Amount": "money",
        "Confirmation Date": "date",
        "Acceptance Status": "text",
    },
    "credit_note": {"Credit Amount": "money", "Reason": "text"},
    "remittance_advice": {"Remitted Amount": "money", "Payment Reference": "text"},
    "assignment_notice": {"Assignee": "text", "Notice Date": "date"},
    "company_registration": {"Registered Name": "text", "Registration Reference": "text"},
    "bank_confirmation": {"Account Masked": "masked", "Bank Institution": "text", "Account Name": "text"},
    "beneficial_ownership": {"Declaration Reference": "text"},
    "insurance_certificate": {"Policy Reference": "text", "Coverage Amount": "money"},
}
COMMON = {
    "Document Type": "text",
    "Document No": "text",
    "Invoice Reference": "text",
    "PO Reference": "text",
    "Supplier Tax ID": "text",
    "Buyer Tax ID": "text",
    "Currency": "text",
}
REQUIRED = {"invoice", "purchase_order", "delivery_note", "goods_receipt", "buyer_confirmation"}


class CaseEntry(LocalModel):
    filename: str = Field(min_length=1, max_length=200)
    document_type: str = Field(min_length=1, max_length=100)


class CaseManifest(LocalModel):
    profile: Literal["goods_receivable_demo"] = "goods_receivable_demo"
    documents: list[CaseEntry] = Field(min_length=2, max_length=12)


def supporting_document(content: bytes, kind: str) -> dict:
    parsed = run_worker("parse", content)
    detected = extract_document(parsed, "invoice")  # Reuse defence, never the invoice projection.
    rows = anchored_rows(parsed.spans, INSTRUCTION)
    fields, reasons = {}, []
    for label, datatype in {**COMMON, **SUPPORT_FIELDS[kind]}.items():
        matches = [
            (text.split(":", 1)[1].strip(), spans)
            for text, spans in rows
            if ":" in text and compact(text.split(":", 1)[0]) == compact(label)
        ]
        candidates = list(dict.fromkeys(value for value, _ in matches if value))
        value, status = None, "missing"
        if len(candidates) > 1:
            status = "conflicting"
        elif len(candidates) == 1:
            value, status = candidates[0], "present"
            try:
                if datatype in {"money", "quantity"}:
                    number = normalize_number(value, "en-US")
                    if number < 0:
                        raise ValueError("Negative supporting amount")
                    value = str(number)
                elif datatype == "date":
                    value = normalize_date(value, None).isoformat()
                elif datatype == "masked" and (not value.startswith("***") or len(value) > 12):
                    raise ValueError("Only masked accounts supported")
                if len(value) > 320:
                    raise ValueError("Field too long")
            except (ValueError, ArithmeticError):
                value, status = None, "unsupported"
        if status != "present":
            reasons.append(f"{label}:{status}")
        fields[label] = {
            "value": value,
            "status": status,
            "evidence_refs": [reference_id(parsed, span) for _, spans in matches for span in spans][:32],
        }
    if fields["Document Type"]["value"] != kind:
        reasons.append("DECLARED_DOCUMENT_TYPE_MISMATCH")
    if detected.injection_flags:
        reasons.append("DOCUMENT_INJECTION_ALERT")
    used_refs = {ref for value in fields.values() for ref in value["evidence_refs"]}
    return {
        "document_type": kind,
        "doc_hash": parsed.doc_hash,
        "fields": fields,
        "evidence": [
            ref.model_dump(mode="json") for ref in detected.document.evidence if ref.ref_id in used_refs
        ],
        "injection_flags": detected.injection_flags,
        "review_reasons": reasons,
        "authenticity": "unknown",
        "extractor": "supporting-labelled-en-v1",
    }


def verify_case(manifest: CaseManifest, uploads: list[tuple[str, bytes]], settings: Settings) -> dict:
    with localcontext(prec=FINANCIAL_DECIMAL_PRECISION):
        return _verify_case(manifest, uploads, settings)


def _verify_case(manifest: CaseManifest, uploads: list[tuple[str, bytes]], settings: Settings) -> dict:
    names = [name for name, _ in uploads]
    declared = [entry.filename for entry in manifest.documents]
    if len(set(names)) != len(names) or len(set(declared)) != len(declared) or set(names) != set(declared):
        raise HTTPException(422, "Uploaded filenames must uniquely match the case manifest")
    types = [entry.document_type for entry in manifest.documents]
    if types.count("invoice") != 1 or types.count("purchase_order") != 1:
        raise HTTPException(422, "Case requires exactly one invoice and one purchase order")
    documents = dict(uploads)
    supporting_by_name = {
        e.filename: supporting_document(documents[e.filename], e.document_type)
        for e in manifest.documents
        if e.document_type in SUPPORT_FIELDS
    }
    invoice = next(documents[e.filename] for e in manifest.documents if e.document_type == "invoice")
    po = next(documents[e.filename] for e in manifest.documents if e.document_type == "purchase_order")
    pair = verify(invoice, po, settings, None)
    reasons = [*pair.review_reasons, "SUPPORTING_DOCUMENT_AUTHENTICITY_UNKNOWN"]
    reasons.extend(f"MISSING_DOCUMENT:{kind}" for kind in sorted(REQUIRED - set(types)))
    supporting, checks = [], []
    hashes = [digest(raw) for _, raw in uploads]
    if len(set(hashes)) != len(hashes):
        reasons.append("DUPLICATE_CASE_DOCUMENT_HASH")
    expected = {
        "Invoice Reference": pair.invoice.document_number.value,
        "PO Reference": pair.purchase_order.document_number.value,
        "Supplier Tax ID": pair.invoice.supplier.legal_identifier.value,
        "Buyer Tax ID": pair.invoice.buyer.legal_identifier.value,
        "Currency": pair.invoice.currency.value,
    }
    credit, remitted = Decimal(0), Decimal(0)
    seen_numbers = set()
    for entry in manifest.documents:
        kind = entry.document_type
        if kind in {"invoice", "purchase_order"}:
            continue
        if kind not in SUPPORT_FIELDS:
            reasons.append(f"UNSUPPORTED_DOCUMENT_TYPE:{kind}")
            supporting.append(
                {
                    "document_type": kind,
                    "doc_hash": digest(documents[entry.filename]),
                    "review_reasons": ["UNSUPPORTED_DOCUMENT_TYPE"],
                    "authenticity": "unknown",
                }
            )
            continue
        result = supporting_by_name[entry.filename]
        supporting.append(result)
        reasons.extend(f"{kind}:{reason}" for reason in result["review_reasons"])
        number = result["fields"]["Document No"]["value"]
        duplicate_number = number is not None and (kind, normalize_reference(number)) in seen_numbers
        if duplicate_number:
            reasons.append(f"DUPLICATE_SUPPORTING_DOCUMENT_NUMBER:{kind}")
        if number is not None:
            seen_numbers.add((kind, normalize_reference(number)))
        linked = not result["review_reasons"] and not duplicate_number
        for label, truth in expected.items():
            field = result["fields"][label]
            observed = field["value"]
            status = (
                "unknown"
                if observed is None or truth is None
                else (
                    "match"
                    if normalize_reference(observed) == normalize_reference(str(truth))
                    else "mismatch"
                )
            )
            checks.append(
                {
                    "document_type": kind,
                    "field": label,
                    "status": status,
                    "evidence_refs": field["evidence_refs"],
                }
            )
            if status != "match":
                linked = False
                reasons.append(f"{kind}:SUPPORTING_REFERENCE_{status.upper()}:{label}")
        for label in ("Shipped Quantity", "Received Quantity"):
            if label in result["fields"]:
                field, unit = result["fields"][label], result["fields"]["Unit"]["value"]
                line = pair.invoice.lines[0] if len(pair.invoice.lines) == 1 else None
                status = "unknown"
                if (
                    line
                    and field["value"] is not None
                    and unit
                    and line.unit.value
                    and line.quantity.value is not None
                ):
                    status = (
                        "match"
                        if (
                            unit.casefold() == line.unit.value.casefold()
                            and Decimal(field["value"]) == line.quantity.value
                        )
                        else "mismatch"
                    )
                checks.append(
                    {
                        "document_type": kind,
                        "field": label,
                        "status": status,
                        "evidence_refs": field["evidence_refs"],
                    }
                )
                if status != "match":
                    reasons.append(f"{kind}:SUPPORTING_QUANTITY_{status.upper()}")
        if kind == "buyer_confirmation":
            accepted = result["fields"]["Accepted Amount"]["value"]
            if (
                accepted is None
                or pair.invoice.amount.value is None
                or Decimal(accepted) != pair.invoice.amount.value
            ):
                reasons.append("BUYER_ACCEPTED_AMOUNT_MISMATCH_OR_UNKNOWN")
            if result["fields"]["Acceptance Status"]["value"] != "accepted":
                reasons.append("BUYER_ACCEPTANCE_UNKNOWN_OR_DISPUTED")
        if linked and kind == "credit_note":
            credit += Decimal(result["fields"]["Credit Amount"]["value"])
        if linked and kind == "remittance_advice":
            remitted += Decimal(result["fields"]["Remitted Amount"]["value"])
    amount = pair.invoice.amount.value
    outstanding = amount - credit - remitted if amount is not None else None
    if outstanding is not None and outstanding < 0:
        reasons.append("DECLARED_ADJUSTMENTS_EXCEED_INVOICE")
    return {
        "schema_version": "ocr-case-evidence-v1",
        "profile": manifest.profile,
        "invoice_po": pair.model_dump(mode="json"),
        "supporting_documents": supporting,
        "checks": checks,
        "review_required": True,
        "review_reasons": sorted(set(reasons)),
        "declared_balance": {
            "invoice_amount": str(amount) if amount is not None else None,
            "credit_amount": str(credit),
            "remitted_amount": str(remitted),
            "outstanding": str(outstanding) if outstanding is not None else None,
            "authoritative": False,
        },
        "financing_authority": False,
    }
