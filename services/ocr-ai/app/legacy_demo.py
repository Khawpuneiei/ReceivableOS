"""Dev-only compatibility for the PM's exact legacy text fixture, not general OCR.

Only the allowlisted original bytes are accepted. All values and offsets come from
printed text; missing jurisdiction, SKU and unit evidence still require review.
"""

import hashlib
import re
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.extract import Extraction
from app.models import DocumentExtraction, EvidenceReference, FieldValue, LineExtraction
from app.validate import validate_document

LEGACY_DEMO_SHA256 = "cc5b3af6d014cdf4ac9cc1c55b151de3706aa970ac381d06b296dd93a823a3ab"


def is_legacy_demo(content: bytes) -> bool:
    return hashlib.sha256(content).hexdigest() == LEGACY_DEMO_SHA256


def extract_legacy_demo(content: bytes) -> Extraction:
    if not is_legacy_demo(content):
        raise ValueError("Only original legacy demo bytes are accepted")
    text = content.decode("utf-8")
    doc_hash = "sha256:" + hashlib.sha256(content).hexdigest()
    evidence = []

    def field(pattern, converter=str):
        match = re.search(pattern, text)
        raw = match[1]
        start, end = match.span(1)
        ref_id = "ev:" + hashlib.sha256(f"{doc_hash}|{start}|{end}".encode()).hexdigest()
        evidence.append(
            EvidenceReference(
                ref_id=ref_id,
                doc_hash=doc_hash,
                page=1,
                source="legacy_text",
                confidence=0.97,
                text_span=(start, end),
            )
        )
        return FieldValue(
            value=converter(raw), raw_value=raw, status="present", confidence=0.97, evidence_refs=[ref_id]
        )

    def money(raw):
        return Decimal(raw.replace(",", ""))

    doc = DocumentExtraction(
        document_id="doc_" + uuid4().hex,
        document_type="invoice",
        doc_hash=doc_hash,
        extractor="development_legacy_text",
    )
    doc.supplier.name = field(r"Supplier: (.*?) \(Tax ID")
    doc.supplier.legal_identifier = field(r"Supplier: .*?Tax ID (\d+)")
    doc.buyer.name = field(r"Buyer: (.*?) \(Tax ID")
    doc.buyer.legal_identifier = field(r"Buyer: .*?Tax ID (\d+)")
    doc.document_number = field(r"TAX INVOICE (\S+)")
    doc.po_reference = field(r"PO: (\S+)")
    doc.issue_date = field(r"Issue date: (\S+)", date.fromisoformat)
    doc.due_date = field(r"Due date: (\S+)", date.fromisoformat)
    doc.currency = field(r"Total\s+[\d,.]+ (THB)")
    doc.amount = field(r"Total\s+([\d,.]+)", money)
    doc.subtotal = field(r"THB\s+([\d,.]+)", money)
    doc.tax_amount = field(r"VAT 7%\s+([\d,.]+)", money)
    doc.lines = [
        LineExtraction(
            description=field(r"\d[\d,]* (food trays)"),
            quantity=field(r"(50,000) food trays", money),
            unit_price=field(r"@ ([\d.]+)", money),
            total=field(r"THB\s+([\d,.]+)", money),
        )
    ]
    doc.evidence = list({ref.ref_id: ref for ref in evidence}.values())
    doc.review_reasons.append("DEVELOPMENT_LEGACY_TEXT_SCOPE_REQUIRES_REVIEW")
    return Extraction(document=validate_document(doc), injection_flags=[], injection_refs=[], private_bank={})
