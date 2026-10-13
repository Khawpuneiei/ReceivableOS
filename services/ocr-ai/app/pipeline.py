"""OCR-local extraction, validation, comparison, and observation history pipeline."""

from __future__ import annotations

import hashlib

from fastapi import HTTPException
from pydantic import Field

from app.compare import compare_documents
from app.config import MAX_OBSERVATIONS, REVIEW_CONFIDENCE, Settings
from app.extract import Extraction, extract_document
from app.fingerprint import (
    bank_token,
    entity_token,
    history_context,
    legacy_fingerprint,
    semantic_fingerprint,
)
from app.fraud import FraudFinding, finding, graph_findings, score
from app.graph import export_graph
from app.history import (
    HistoryCapacityError,
    HistoryConflictError,
    HistoryContextError,
    InvoiceObservation,
    ObservationStore,
)
from app.ingest import detect_format, digest, run_worker
from app.llm_client import configured, read_hosted_candidates
from app.models import (
    ConsumerHandoff,
    DocumentExtraction,
    EvidenceReference,
    Fingerprint,
    FraudGraph,
    InvoicePoVerificationResult,
)
from app.normalize import normalize_date, normalize_number
from app.qwen import read_candidates
from app.validate import CRITICAL_FIELDS, validate_document
from shared.schemas import ExtractedInvoice, LineItem, Party


class OcrExtractResponse(ExtractedInvoice):
    document_evidence: DocumentExtraction
    semantic_fingerprint: Fingerprint | None = None
    validation_flags: list[str] = Field(default_factory=list)
    fraud_details: list[FraudFinding] = Field(default_factory=list)
    review_required: bool
    extractor: str
    model_version: str = "spatial-rules-v2"
    fraud_graph: FraudGraph | None = None
    handoff: ConsumerHandoff | None = None
    model_checks: list[dict[str, str]] = Field(default_factory=list)


def extract(content: bytes, document_type: str, settings: Settings) -> Extraction:
    if settings.development_mode and document_type == "invoice" and detect_format(content) is None:
        from app.legacy_demo import extract_legacy_demo

        return extract_legacy_demo(content)
    parsed = run_worker("parse", content)
    readable_pages = {span.page for span in parsed.spans if span.text.strip() and not span.hidden}
    unreadable_pages = set(range(1, len(parsed.images) + 1)) - readable_pages
    missing_page_review = False
    if unreadable_pages:
        if not settings.paddle_enabled:
            if not readable_pages:
                raise HTTPException(422, "Image or scanned document requires a configured local OCR engine")
            missing_page_review = True
        else:
            ocr = run_worker("paddle", content)
            added = [span for span in ocr.spans if span.page in unreadable_pages]
            added = [
                span.model_copy(update={"ordinal": len(parsed.spans) + index})
                for index, span in enumerate(added)
            ]
            parsed = parsed.model_copy(
                update={"spans": [*parsed.spans, *added], "engine": f"{parsed.engine}+{ocr.engine}"}
            )
            missing_page_review = not all(
                any(span.page == page and span.text.strip() for span in added) for page in unreadable_pages
            )
    result = extract_document(parsed, document_type)
    doc = result.document
    if missing_page_review:
        doc.review_reasons.append("UNREADABLE_PAGES_REQUIRE_OCR")
    readers = []
    if settings.qwen_enabled:
        if len(parsed.images) > 1:
            doc.review_reasons.append("QWEN_FIRST_PAGE_ONLY")
        readers.append(("QWEN", read_candidates(parsed.images, settings)))
    if configured():
        hosted, cache_status = read_hosted_candidates(parsed.images)
        result.model_checks.append({"provider": "hosted", "cache": cache_status})
        readers.append(("HOSTED_LLM", hosted))
    for reader, candidates in readers:
        if candidates is None:
            doc.review_reasons.append(f"{reader}_UNAVAILABLE_OR_INVALID")
        else:
            if all(
                getattr(candidates, name) is None
                for name in (
                    "document_number",
                    "amount",
                    "currency",
                    "supplier_name",
                    "buyer_name",
                    "issue_date",
                    "due_date",
                )
            ):
                doc.review_reasons.append(f"{reader}_NO_SUPPORTED_CANDIDATES")
            if candidates.instructions_found:
                result.injection_flags.append("LLM_REPORTED")
                doc.review_reasons.append("DOCUMENT_INJECTION_ALERT")
            for party in ("supplier", "buyer"):
                proposed = getattr(candidates, f"{party}_name")
                observed = getattr(doc, party).name.value
                if proposed is not None and observed is not None and proposed != observed:
                    doc.review_reasons.append(f"{reader}_DISAGREEMENT:{party}.name")
            for name in ("document_number", "po_reference", "issue_date", "due_date", "amount", "currency"):
                proposed, observed = getattr(candidates, name), getattr(doc, name)
                if proposed is None or observed.value is None:
                    continue
                try:
                    normalized = (
                        normalize_number(
                            proposed, doc.locale_evidence[0] if len(set(doc.locale_evidence)) == 1 else None
                        )
                        if name == "amount"
                        else proposed
                    )
                    if name in {"issue_date", "due_date"}:
                        normalized = normalize_date(proposed, None)
                    if normalized != observed.value:
                        doc.review_reasons.append(f"{reader}_DISAGREEMENT:{name}")
                except (ValueError, ArithmeticError):
                    doc.review_reasons.append(f"{reader}_UNGROUNDED:{name}")
    result.document = validate_document(doc)
    return result


def require_secrets(settings: Settings) -> None:
    if not settings.fingerprint_key:
        raise HTTPException(503, "Fingerprint HMAC secret is not configured")


def compatible_invoice(result: Extraction, settings: Settings) -> OcrExtractResponse | None:
    doc = result.document
    required = [*(getattr(doc, name) for name in CRITICAL_FIELDS), doc.supplier.name, doc.buyer.name]
    if any(field.status != "present" for field in required):
        return None
    confidence = min(field.confidence for field in required)
    if doc.review_reasons:
        confidence = min(confidence, REVIEW_CONFIDENCE - 0.01)
    # v1 omits jurisdiction and rounds to two decimals; local v2 prevents local international collisions.
    if doc.amount.value.as_tuple().exponent < -2 or any(
        party.country.value != "TH" or party.identifier_scheme.value != "TAX_ID"
        for party in (doc.supplier, doc.buyer)
    ):
        doc.review_reasons.append("LEGACY_FINGERPRINT_SCOPE_REQUIRES_REVIEW")
        confidence = min(confidence, REVIEW_CONFIDENCE - 0.01)
    lines = [
        LineItem(
            description=line.description.value,
            qty=line.quantity.value,
            unit_price=line.unit_price.value,
            total=line.total.value,
        )
        for line in doc.lines
        if all(
            field.status == "present"
            for field in [line.description, line.quantity, line.unit_price, line.total]
        )
    ]
    return OcrExtractResponse(
        invoice_id=f"inv_{doc.document_id[4:]}",
        supplier=Party(name=doc.supplier.name.value, tax_id=doc.supplier.legal_identifier.value),
        buyer=Party(name=doc.buyer.name.value, tax_id=doc.buyer.legal_identifier.value),
        invoice_no=doc.document_number.value,
        issue_date=doc.issue_date.value,
        due_date=doc.due_date.value,
        amount=doc.amount.value,
        currency=doc.currency.value,
        line_items=lines,
        confidence=confidence,
        injection_flags=list(dict.fromkeys(result.injection_flags)),
        fraud_score=0,
        fraud_flags=[],
        doc_hash=doc.doc_hash,
        invoice_fingerprint=legacy_fingerprint(doc, settings.fingerprint_key),
        document_evidence=doc,
        semantic_fingerprint=semantic_fingerprint(doc, settings.fingerprint_key),
        validation_flags=list(dict.fromkeys(doc.review_reasons)),
        review_required=bool(doc.review_reasons),
        extractor=doc.extractor,
        model_checks=result.model_checks,
    )


def observe(
    result: Extraction,
    settings: Settings,
    request_digest: str,
    idempotency_key: str | None,
    initial_findings: list[FraudFinding],
    contextual_evidence: list[EvidenceReference] | None = None,
) -> tuple[str, list[FraudFinding], FraudGraph]:
    doc, private_bank = result.document, result.private_bank
    if private_bank.get("account") and float(private_bank.get("confidence", "1")) < REVIEW_CONFIDENCE:
        doc.review_reasons.append("BANK_LOW_CONFIDENCE")
        tokenized_bank = None
    elif private_bank.get("account") and (not private_bank.get("scheme") or not private_bank.get("country")):
        doc.review_reasons.append("BANK_SCOPE_UNKNOWN")
        tokenized_bank = None
    elif (
        private_bank.get("account")
        and private_bank.get("scheme") == "LOCAL"
        and not private_bank.get("institution")
    ):
        doc.review_reasons.append("BANK_INSTITUTION_UNKNOWN")
        tokenized_bank = None
    else:
        try:
            tokenized_bank = bank_token(private_bank, settings.bank_key)
        except ValueError as exc:
            raise HTTPException(503, "Bank token HMAC secret is not configured") from exc
    critical_refs = [ref for name in CRITICAL_FIELDS for ref in getattr(doc, name).evidence_refs]
    party_refs = [
        ref
        for party in (doc.supplier, doc.buyer)
        for field in (party.legal_identifier, party.country, party.identifier_scheme)
        for ref in field.evidence_refs
    ]
    party_refs.extend(
        private_bank[key]
        for key in ("account_ref", "country_ref", "scheme_ref", "institution_ref")
        if key in private_bank
    )
    evidence_by_id = {ref.ref_id: ref for ref in [*doc.evidence, *(contextual_evidence or [])]}
    observation_refs = list(
        dict.fromkeys(
            [*party_refs, *critical_refs, *(ref for item in initial_findings for ref in item.evidence_refs)]
        )
    )[:32]
    observation = InvoiceObservation(
        doc_hash=doc.doc_hash,
        semantic_fingerprint=semantic_fingerprint(doc, settings.fingerprint_key),
        invoice_number=doc.document_number.value,
        amount=doc.amount.value,
        currency=doc.currency.value,
        issue_date=doc.issue_date.value,
        supplier_token=entity_token(doc.supplier, settings.fingerprint_key),
        buyer_token=entity_token(doc.buyer, settings.fingerprint_key),
        bank_token=tokenized_bank,
        evidence_refs=observation_refs,
        evidence=[evidence_by_id[ref] for ref in observation_refs if ref in evidence_by_id],
        anomaly_codes=[item.code for item in initial_findings],
    )
    store = ObservationStore(
        settings.state_path,
        max_observations=MAX_OBSERVATIONS,
        context_digest=history_context(settings.fingerprint_key, settings.bank_key),
    )
    try:
        history = store.observe(observation, request_digest=request_digest, idempotency_key=idempotency_key)
        records = store.observations()
    except HistoryContextError as exc:
        raise HTTPException(
            503, "OCR history identity context changed or is unversioned; operator migration is required"
        ) from exc
    except ValueError as exc:
        if not isinstance(exc, (HistoryConflictError, HistoryCapacityError)):
            raise HTTPException(422, "Invalid observation or idempotency metadata") from exc
        if isinstance(exc, HistoryCapacityError):
            raise HTTPException(
                503, "OCR observation history is at capacity; operator review is required"
            ) from exc
        raise HTTPException(409, "Idempotency key is bound to a different upload request") from exc
    findings = list(initial_findings)
    duplicate_codes = set()
    for duplicate in history.duplicates:
        if duplicate.code in duplicate_codes:
            continue
        duplicate_codes.add(duplicate.code)
        findings.append(
            finding(
                duplicate.code,
                "Previously observed invoice evidence; this does not establish prior financing",
                [*observation.evidence_refs, *duplicate.evidence_refs],
                path=[history.observation_id, duplicate.previous_observation_id],
            )
        )
    index = next(index for index, (oid, _) in enumerate(records) if oid == history.observation_id)
    findings.extend(graph_findings(records[: index + 1], history.observation_id))
    for _, record in records[: index + 1]:
        evidence_by_id.update({ref.ref_id: ref for ref in record.evidence})
    for item in findings:
        item.evidence_refs = list(dict.fromkeys(item.evidence_refs))[:128]
        item.evidence = [evidence_by_id[ref] for ref in item.evidence_refs if ref in evidence_by_id]
    return (
        history.observation_id,
        findings,
        export_graph(records[: index + 1], history.observation_id, findings),
    )


def consumer_handoff(observation_id, documents, findings, reasons, injection_flags) -> ConsumerHandoff:
    return ConsumerHandoff(
        observation_id=observation_id,
        document_hashes=[doc.doc_hash for doc in documents],
        review_required=bool(reasons or injection_flags or findings),
        review_reasons=list(dict.fromkeys(reasons)),
        injection_flags=list(dict.fromkeys(injection_flags)),
        fraud_codes=list(dict.fromkeys(item.code for item in findings)),
        fraud_score=score(findings),
    )


def validation_findings(doc: DocumentExtraction) -> list[FraudFinding]:
    if any(
        reason.startswith(("LINE_MATH_MISMATCH", "LINE_SUM_MISMATCH", "TOTAL_MISMATCH"))
        for reason in doc.review_reasons
    ):
        refs = [
            ref for name in ("amount", "subtotal", "tax_amount") for ref in getattr(doc, name).evidence_refs
        ]
        return [finding("math_inconsistent", "Printed line or tax arithmetic is inconsistent", refs)]
    return []


def extract_invoice(content: bytes, settings: Settings, idempotency_key: str | None) -> OcrExtractResponse:
    require_secrets(settings)
    result = extract(content, "invoice", settings)
    response = compatible_invoice(result, settings)
    if response is None:
        raise HTTPException(
            422,
            "Required invoice fields are missing, conflicting, ambiguous, or unsupported; "
            "use local pair verification for partial review evidence",
        )
    observation_id, findings, graph = observe(
        result,
        settings,
        digest(b"extract-v1\0" + content),
        idempotency_key,
        validation_findings(result.document),
    )
    response.invoice_id = observation_id
    response.fraud_details, response.fraud_flags = (
        findings,
        list(dict.fromkeys(item.code for item in findings)),
    )
    response.fraud_score = score(findings)
    response.review_required = bool(result.document.review_reasons or findings)
    response.validation_flags = list(dict.fromkeys(result.document.review_reasons))
    if response.review_required:
        response.confidence = min(response.confidence, REVIEW_CONFIDENCE - 0.01)
    response.fraud_graph = graph
    response.handoff = consumer_handoff(
        observation_id, [result.document], findings, response.validation_flags, response.injection_flags
    )
    return response


def verify(
    invoice_bytes: bytes, po_bytes: bytes, settings: Settings, idempotency_key: str | None
) -> InvoicePoVerificationResult:
    require_secrets(settings)
    invoice_result = extract(invoice_bytes, "invoice", settings)
    po_result = extract(po_bytes, "purchase_order", settings)
    checks = compare_documents(invoice_result.document, po_result.document)
    findings = validation_findings(invoice_result.document)
    for check in checks:
        if check.status != "mismatch":
            continue
        code = None
        if check.field in {"amount", "subtotal", "tax_amount"}:
            code = "po_amount_mismatch"
        elif check.field.endswith(".identity"):
            code = "po_party_mismatch"
        elif check.field == "currency":
            code = "po_currency_mismatch"
        if code and code not in {item.code for item in findings}:
            findings.append(
                finding(
                    code,
                    "Uploaded invoice and PO have conflicting grounded fields",
                    [*check.invoice_evidence_refs, *check.po_evidence_refs],
                )
            )
    pair_digest = digest(
        b"verify-v1\0" + hashlib.sha256(invoice_bytes).digest() + hashlib.sha256(po_bytes).digest()
    )
    observation_id, findings, graph = observe(
        invoice_result, settings, pair_digest, idempotency_key, findings, po_result.document.evidence
    )
    compatible = compatible_invoice(invoice_result, settings)
    if compatible:
        compatible.invoice_id = observation_id
        compatible.fraud_details, compatible.fraud_flags = (
            findings,
            list(dict.fromkeys(item.code for item in findings)),
        )
        compatible.fraud_score = score(findings)
        compatible.review_required = bool(invoice_result.document.review_reasons or findings)
        if compatible.review_required:
            compatible.confidence = min(compatible.confidence, REVIEW_CONFIDENCE - 0.01)
    reasons = [
        *(["PAIR_MISMATCH_REQUIRES_REVIEW"] if any(check.status == "mismatch" for check in checks) else []),
        *invoice_result.document.review_reasons,
        *po_result.document.review_reasons,
        *(check.rule_code for check in checks if check.status in {"unknown", "mismatch"}),
        *(item.code for item in findings),
    ]
    status = (
        "mismatch"
        if any(check.status == "mismatch" for check in checks)
        else "review"
        if reasons
        else "matched"
    )
    handoff = consumer_handoff(
        observation_id,
        [invoice_result.document, po_result.document],
        findings,
        reasons,
        [*invoice_result.injection_flags, *po_result.injection_flags],
    )
    if compatible:
        compatible.review_required = handoff.review_required
        compatible.validation_flags = handoff.review_reasons
        compatible.injection_flags = handoff.injection_flags
        if compatible.review_required:
            compatible.confidence = min(compatible.confidence, REVIEW_CONFIDENCE - 0.01)
    return InvoicePoVerificationResult(
        status=status,
        invoice=invoice_result.document,
        purchase_order=po_result.document,
        compatible_invoice=compatible,
        checks=checks,
        review_reasons=list(dict.fromkeys(reasons)),
        fraud_details=findings,
        fraud_graph=graph,
        handoff=handoff,
    )
