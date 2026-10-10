"""Label-based extraction from actual source spans; optimized for documented templates."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from uuid import uuid4

from app.config import FIELD_CONFIDENCE
from app.ingest import ParsedDocument, Span
from app.layout import anchored_rows, compact, source_rows, table_rows
from app.models import DocumentExtraction, EvidenceReference, FieldValue, LineExtraction
from app.normalize import normalize_country, normalize_currency, normalize_date, normalize_number

LABELS = {
    "document_number": ("Invoice No", "Invoice Number", "เลขที่ใบแจ้งหนี้"),
    "po_reference": ("PO No", "PO Number", "เลขที่ใบสั่งซื้อ"),
    "supplier.name": ("Supplier", "Seller", "ผู้ขาย"),
    "buyer.name": ("Buyer", "ผู้ซื้อ"),
    "supplier.legal_identifier": ("Supplier Tax ID", "Supplier Legal ID", "เลขภาษีผู้ขาย"),
    "buyer.legal_identifier": ("Buyer Tax ID", "Buyer Legal ID", "เลขภาษีผู้ซื้อ"),
    "supplier.country": ("Supplier Country", "ประเทศผู้ขาย"),
    "buyer.country": ("Buyer Country", "ประเทศผู้ซื้อ"),
    "supplier.identifier_scheme": ("Supplier ID Scheme", "ประเภทเลขผู้ขาย"),
    "buyer.identifier_scheme": ("Buyer ID Scheme", "ประเภทเลขผู้ซื้อ"),
    "issue_date": ("Issue Date", "Order Date", "วันที่ออก"),
    "due_date": ("Due Date", "วันครบกำหนด"),
    "currency": ("Currency", "สกุลเงิน"),
    "amount": ("Total", "Grand Total", "ยอดรวม"),
    "subtotal": ("Subtotal", "ยอดก่อนภาษี"),
    "tax_amount": ("Tax", "VAT Amount", "ภาษี"),
    "tax_basis": ("Tax Basis", "ฐานภาษี"),
    "detected_language": ("Language", "ภาษา"),
}
CHINESE_LABELS = {
    "document_number": ("发票号码", "发票编号"),
    "po_reference": ("采购订单号",),
    "supplier.name": ("供应商",),
    "buyer.name": ("买方",),
    "supplier.legal_identifier": ("供应商税号",),
    "buyer.legal_identifier": ("买方税号",),
    "supplier.country": ("供应商国家",),
    "buyer.country": ("买方国家",),
    "supplier.identifier_scheme": ("供应商证件类型", "供应商标识类型"),
    "buyer.identifier_scheme": ("买方证件类型", "买方标识类型"),
    "issue_date": ("开票日期",),
    "due_date": ("到期日期",),
    "currency": ("货币", "币种"),
    "amount": ("总额", "价税合计"),
    "subtotal": ("小计",),
    "tax_amount": ("税额",),
    "tax_basis": ("计税方式", "税务基础"),
    "detected_language": ("语言",),
}
for _key, _labels in CHINESE_LABELS.items():
    LABELS[_key] += _labels
EMBEDDED_LABEL = re.compile(
    r"(?:^|\s)(?:" + "|".join(re.escape(label) for labels in LABELS.values() for label in labels) + r")\s*:",
    re.IGNORECASE,
)
INSTRUCTION = re.compile(
    r"ignore.{0,25}(instructions|rules)|\b(system|assistant|developer)\s*:|advance[_ ]rate|"
    r"approve.{0,25}(invoice|transaction|100%)|ไม่ต้องตรวจ|อนุมัติทันที|忽略.{0,8}指令",
    re.IGNORECASE,
)
BANK_LABELS = {
    "bankaccount": "account",
    "bankcountry": "country",
    "bankscheme": "scheme",
    "bankinstitution": "institution",
    "银行账号": "account",
    "银行国家": "country",
    "银行账户类型": "scheme",
    "银行机构": "institution",
}


@dataclass
class Extraction:
    document: DocumentExtraction
    private_bank: dict[str, str]
    injection_flags: list[str]
    injection_refs: list[str]


def reference_id(parsed: ParsedDocument, span: Span) -> str:
    text = f"{parsed.doc_hash}|{span.source}|{span.page}|{span.ordinal}"
    return "ev:" + hashlib.sha256(text.encode()).hexdigest()


def extract_document(parsed: ParsedDocument, document_type: str) -> Extraction:
    references = [
        EvidenceReference(
            ref_id=reference_id(parsed, span),
            doc_hash=parsed.doc_hash,
            page=span.page,
            source=span.source,
            bbox=span.bbox,
            confidence=span.confidence,
        )
        for span in parsed.spans
    ]
    doc = DocumentExtraction(
        document_id=f"doc_{uuid4().hex}",
        document_type=document_type,
        doc_hash=parsed.doc_hash,
        extractor=parsed.engine,
        evidence=references,
    )
    injection_flags, injection_refs = [], []
    for span in parsed.spans:
        invisible = any(unicodedata.category(char) == "Cf" for char in span.text)
        if span.hidden:
            injection_flags.append("HIDDEN_TEXT")
        if invisible:
            injection_flags.append("UNICODE_OBFUSCATION")
        if INSTRUCTION.search(span.text):
            injection_flags.append("VISIBLE_INSTRUCTION" if not span.hidden else "HIDDEN_TEXT")
        if span.hidden or invisible or INSTRUCTION.search(span.text):
            injection_refs.append(reference_id(parsed, span))
    if any(INSTRUCTION.search(text) for text in parsed.metadata_text):
        injection_flags.append("METADATA_INJECTION")
    rows = anchored_rows(parsed.spans, INSTRUCTION)
    locale_matches = [
        text.split(":", 1)[1].strip()
        for text, _ in rows
        if compact(text.split(":", 1)[0]) in {compact("Locale"), compact("โลแคล"), "区域设置"}
    ]
    locale = locale_matches[0] if len(set(locale_matches)) == 1 else None
    doc.locale_evidence = locale_matches[:16]
    raw_fields: dict[str, list[tuple[str, list[Span]]]] = {}
    private_bank: dict[str, str] = {}
    observed_accounts = []
    for text, spans in rows:
        for key, labels in LABELS.items():
            for label in labels:
                if compact(text.split(":", 1)[0]) == compact(label):
                    raw_fields.setdefault(key, []).append((text.split(":", 1)[1].strip(), spans))
                    break
        bank_key = BANK_LABELS.get(compact(text.split(":", 1)[0]))
        if bank_key:
            key, bank_value = bank_key, text.split(":", 1)[1].strip()
            if key in private_bank and private_bank[key] != bank_value:
                doc.review_reasons.append("BANK_EVIDENCE_CONFLICT")
                private_bank["conflict"] = "1"
            private_bank[key] = bank_value
            private_bank[f"{key}_ref"] = reference_id(parsed, spans[0])
            if key == "account":
                observed_accounts.append(bank_value)
                private_bank["evidence_ref"] = reference_id(parsed, spans[0])
            private_bank["confidence"] = str(
                min(float(private_bank.get("confidence", "1")), min(span.confidence for span in spans))
            )
    if private_bank.get("country"):
        try:
            private_bank["country"] = normalize_country(private_bank["country"])
        except ValueError:
            private_bank.pop("country")
            doc.review_reasons.append("BANK_COUNTRY_UNRESOLVED")
    if private_bank.get("scheme"):
        private_bank["scheme"] = private_bank["scheme"].upper()
        if private_bank["scheme"] not in {"LOCAL", "IBAN"}:
            private_bank.pop("scheme")
            doc.review_reasons.append("BANK_SCHEME_UNSUPPORTED")
    if document_type == "purchase_order":
        raw_fields["document_number"] = raw_fields.get("po_reference", [])
    for field_name, observations in raw_fields.items():
        if not observations:
            continue
        raw, spans = observations[0]
        refs = [reference_id(parsed, span) for _, source_spans in observations for span in source_spans][:32]
        value = raw
        status = "present"
        if len({value for value, _ in observations}) > 1:
            status, value = "conflicting", None
        elif EMBEDDED_LABEL.search(raw):
            # A neighboring field label is evidence of an unresolved row/column boundary.
            status, value = "ambiguous", None
        else:
            try:
                if field_name in {"amount", "subtotal", "tax_amount"}:
                    value = normalize_number(raw, locale)
                elif field_name in {"issue_date", "due_date"}:
                    value = normalize_date(raw, locale)
                elif field_name.endswith(".country"):
                    value = normalize_country(raw)
                elif field_name.endswith(".identifier_scheme"):
                    value = raw.strip().upper()
                elif field_name == "currency":
                    value = normalize_currency(raw)
                elif field_name == "tax_basis" and raw not in {"inclusive", "exclusive", "exempt"}:
                    raise ValueError("Unsupported tax basis")
            except (ValueError, ArithmeticError):
                status, value = "ambiguous", None
        field = FieldValue(
            value=value,
            raw_value=raw[:1024],
            status=status,
            evidence_refs=list(dict.fromkeys(refs)),
            confidence=FIELD_CONFIDENCE * min(span.confidence for span in spans)
            if status == "present"
            else 0,
        )
        if "." in field_name:
            party, attribute = field_name.split(".")
            setattr(getattr(doc, party), attribute, field)
        else:
            setattr(doc, field_name, field)
        if status != "present":
            doc.review_reasons.append(f"{status.upper()}:{field_name}")
    line_rows = []
    for text, spans in rows:
        if compact(text.split(":", 1)[0]) not in {"item", compact("รายการ"), "明细", "项目"}:
            continue
        line_rows.append(([part.strip() for part in text.split(":", 1)[1].split("|")], spans))
    tables, incomplete_table = table_rows(parsed.spans, INSTRUCTION)
    if incomplete_table:
        doc.review_reasons.append("LINE_LAYOUT_UNSUPPORTED")
    # Two competing representations are ambiguous, rather than double-counted.
    if tables and line_rows:
        doc.review_reasons.append("LINE_LAYOUT_UNSUPPORTED")
    else:
        line_rows.extend(tables)
    for parts, spans in line_rows:
        if len(parts) != 5:
            doc.review_reasons.append("LINE_LAYOUT_UNSUPPORTED")
            continue
        refs = [reference_id(parsed, span) for span in spans]
        confidence = FIELD_CONFIDENCE * min(span.confidence for span in spans)

        def line_field(raw: str, *, numeric: bool = False, refs=refs, confidence=confidence) -> FieldValue:
            try:
                value = normalize_number(raw, locale) if numeric else raw
            except (ValueError, ArithmeticError):
                return FieldValue(raw_value=raw, status="ambiguous", evidence_refs=refs)
            return FieldValue(
                value=value, raw_value=raw, status="present", confidence=confidence, evidence_refs=refs
            )

        doc.lines.append(
            LineExtraction(
                sku=line_field(parts[0]),
                description=line_field(parts[1]),
                quantity=line_field(parts[2], numeric=True),
                unit_price=line_field(parts[3], numeric=True),
                total=line_field(parts[4], numeric=True),
            )
        )
    if observed_accounts:
        normalized_accounts = [
            re.sub(r"[\s-]", "", unicodedata.normalize("NFKC", account)).casefold()
            for account in observed_accounts
        ]

        def redact(node):
            if isinstance(node, FieldValue):
                raw = node.raw_value or ""
                compact = re.sub(r"[\s-]", "", unicodedata.normalize("NFKC", raw)).casefold()
                if any(account and account in compact for account in normalized_accounts):
                    node.value = None
                    node.raw_value = "[REDACTED BANK ACCOUNT]"
                    node.status = "conflicting"
                    node.confidence = 0
                    doc.review_reasons.append("BANK_VALUE_IN_PUBLIC_FIELD")
                return
            if hasattr(type(node), "model_fields"):
                for name in type(node).model_fields:
                    child = getattr(node, name)
                    if isinstance(child, list):
                        for item in child:
                            redact(item)
                    elif hasattr(type(child), "model_fields"):
                        redact(child)

        redact(doc)
    # Script claims require observed script support; declared metadata cannot grant support.
    letters = [
        char
        for row in source_rows(parsed.spans, INSTRUCTION)
        for span in row
        for char in span.text
        if char.isalpha()
    ]
    if any("CJK UNIFIED" in unicodedata.name(char, "") for char in letters):
        doc.review_reasons.append("EXPERIMENTAL_CHINESE_REQUIRES_REVIEW")
    if any(
        not any(script in unicodedata.name(char, "") for script in ("LATIN", "THAI", "CJK UNIFIED"))
        for char in letters
    ):
        doc.review_reasons.append("UNSUPPORTED_SCRIPT")
    if not letters:
        doc.review_reasons.append("NO_READABLE_TEXT")
    if injection_flags:
        doc.review_reasons.append("DOCUMENT_INJECTION_ALERT")
    doc.review_reasons = list(dict.fromkeys(doc.review_reasons))
    return Extraction(
        DocumentExtraction.model_validate(doc.model_dump()),
        private_bank,
        list(dict.fromkeys(injection_flags)),
        list(dict.fromkeys(injection_refs)),
    )
