"""OCR-local evidence contracts; shared integration models remain unchanged."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import REVIEW_CONFIDENCE
from shared.schemas import ExtractedInvoice

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
EvidenceId = Annotated[str, Field(pattern=r"^ev:[0-9a-f]{64}$")]
Fingerprint = Annotated[str, Field(pattern=r"^0x[0-9a-f]{64}$")]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
T = TypeVar("T")


class LocalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class EvidenceReference(LocalModel):
    ref_id: EvidenceId
    doc_hash: Digest
    page: int = Field(ge=1)
    source: Literal["pdf_text", "image_ocr", "legacy_text"]
    confidence: float = Field(ge=0, le=1)
    bbox: tuple[float, float, float, float] | None = None
    text_span: tuple[int, int] | None = None

    @model_validator(mode="after")
    def valid_location(self) -> EvidenceReference:
        if self.bbox is None and self.text_span is None:
            raise ValueError("Evidence must have a bounding box or text span")
        if self.bbox and (self.bbox[2] < self.bbox[0] or self.bbox[3] < self.bbox[1]):
            raise ValueError("Invalid evidence bounding box")
        if self.text_span and (self.text_span[0] < 0 or self.text_span[1] <= self.text_span[0]):
            raise ValueError("Invalid evidence text span")
        return self


class FieldValue(LocalModel, Generic[T]):
    value: T | None = None
    raw_value: str | None = Field(default=None, max_length=1024)
    status: Literal["present", "missing", "ambiguous", "conflicting", "unsupported"] = "missing"
    confidence: float = Field(default=0, ge=0, le=1)
    evidence_refs: list[EvidenceId] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def require_grounding(self) -> FieldValue[T]:
        if self.status == "present":
            if self.value is None or not self.raw_value or not self.evidence_refs or self.confidence <= 0:
                raise ValueError("Present fields require a value, raw evidence, references, and confidence")
        elif self.value is not None:
            raise ValueError("Unresolved fields cannot contain a normalized value")
        return self


class PartyExtraction(LocalModel):
    name: FieldValue[str] = Field(default_factory=FieldValue[str])
    legal_identifier: FieldValue[str] = Field(default_factory=FieldValue[str])
    country: FieldValue[str] = Field(default_factory=FieldValue[str])
    identifier_scheme: FieldValue[str] = Field(default_factory=FieldValue[str])


class LineExtraction(LocalModel):
    description: FieldValue[str] = Field(default_factory=FieldValue[str])
    sku: FieldValue[str] = Field(default_factory=FieldValue[str])
    quantity: FieldValue[Decimal] = Field(default_factory=FieldValue[Decimal])
    unit: FieldValue[str] = Field(default_factory=FieldValue[str])
    unit_price: FieldValue[Decimal] = Field(default_factory=FieldValue[Decimal])
    total: FieldValue[Decimal] = Field(default_factory=FieldValue[Decimal])


class DocumentExtraction(LocalModel):
    """Partial evidence is explicit; no bank-account value belongs in this public model."""

    document_id: str = Field(pattern=r"^doc_[0-9a-f]{32}$")
    document_type: Literal["invoice", "purchase_order"]
    doc_hash: Digest
    extractor: str = Field(max_length=100)
    supplier: PartyExtraction = Field(default_factory=PartyExtraction)
    buyer: PartyExtraction = Field(default_factory=PartyExtraction)
    document_number: FieldValue[str] = Field(default_factory=FieldValue[str])
    po_reference: FieldValue[str] = Field(default_factory=FieldValue[str])
    issue_date: FieldValue[date] = Field(default_factory=FieldValue[date])
    due_date: FieldValue[date] = Field(default_factory=FieldValue[date])
    currency: FieldValue[CurrencyCode] = Field(default_factory=FieldValue[CurrencyCode])
    amount: FieldValue[Decimal] = Field(default_factory=FieldValue[Decimal])
    subtotal: FieldValue[Decimal] = Field(default_factory=FieldValue[Decimal])
    tax_amount: FieldValue[Decimal] = Field(default_factory=FieldValue[Decimal])
    tax_basis: FieldValue[Literal["inclusive", "exclusive", "exempt"]] = Field(default_factory=FieldValue)
    detected_language: FieldValue[str] = Field(default_factory=FieldValue[str])
    locale_evidence: list[str] = Field(default_factory=list, max_length=16)
    lines: list[LineExtraction] = Field(default_factory=list, max_length=500)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=10000)
    review_reasons: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_evidence(self) -> DocumentExtraction:
        refs = {reference.ref_id for reference in self.evidence}
        if len(refs) != len(self.evidence):
            raise ValueError("Evidence references must be unique")
        if any(reference.doc_hash != self.doc_hash for reference in self.evidence):
            raise ValueError("Evidence references must belong to this document")

        def visit(node: BaseModel) -> None:
            if isinstance(node, FieldValue):
                if not set(node.evidence_refs) <= refs:
                    raise ValueError("Field evidence reference is unresolved")
                return
            for name in type(node).model_fields:
                child = getattr(node, name)
                if isinstance(child, BaseModel):
                    visit(child)
                elif isinstance(child, list):
                    for item in child:
                        if isinstance(item, BaseModel):
                            visit(item)

        visit(self)
        return self


class ComparisonCheck(LocalModel):
    field: str = Field(max_length=100)
    status: Literal["match", "mismatch", "unknown"]
    rule_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,99}$")
    invoice_value: str | None = Field(default=None, max_length=1024)
    po_value: str | None = Field(default=None, max_length=1024)
    invoice_evidence_refs: list[EvidenceId] = Field(default_factory=list, max_length=32)
    po_evidence_refs: list[EvidenceId] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def require_two_sources(self) -> ComparisonCheck:
        if self.status != "unknown":
            if not self.invoice_evidence_refs or not self.po_evidence_refs:
                raise ValueError("Resolved comparisons require evidence from both documents")
            if self.invoice_value is None or self.po_value is None:
                raise ValueError("Resolved comparisons require values from both documents")
        return self


class FraudFinding(LocalModel):
    code: str
    weight: float = Field(ge=0, le=1)
    reason: str
    evidence_refs: list[EvidenceId] = Field(default_factory=list, max_length=128)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=128)
    entity_refs: list[str] = Field(default_factory=list)
    path: list[str] = Field(default_factory=list)
    rule_version: str = "graph-rules-v2"


class GraphNode(LocalModel):
    node_id: str
    node_type: Literal["invoice", "company", "bank_account_token"]
    doc_hash: Digest | None = None


class GraphEdge(LocalModel):
    source: str
    target: str
    relation: Literal[
        "ISSUED_BY",
        "BILLED_TO",
        "PAYABLE_TO",
        "DUPLICATE_CANDIDATE",
        "SIMILAR_REFERENCE",
        "BANK_ACCOUNT_CHANGED_CANDIDATE",
    ]
    evidence_refs: list[EvidenceId] = Field(default_factory=list, max_length=128)


class FraudGraph(LocalModel):
    schema_version: Literal["ocr-graph-v2"] = "ocr-graph-v2"
    scope: Literal["current_observation_and_findings"] = "current_observation_and_findings"
    nodes: list[GraphNode] = Field(default_factory=list, max_length=2000)
    edges: list[GraphEdge] = Field(default_factory=list, max_length=2500)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=16000)

    @model_validator(mode="after")
    def resolved_graph(self) -> FraudGraph:
        nodes = {node.node_id for node in self.nodes}
        refs = {item.ref_id for item in self.evidence}
        if len(nodes) != len(self.nodes) or len(refs) != len(self.evidence):
            raise ValueError("Graph identifiers must be unique")
        for edge in self.edges:
            if edge.source not in nodes or edge.target not in nodes or not edge.evidence_refs:
                raise ValueError("Graph relationships require nodes and evidence")
            if not set(edge.evidence_refs) <= refs:
                raise ValueError("Graph evidence location is unresolved")
        return self


class ConsumerHandoff(LocalModel):
    """Unsigned service-local evidence for downstream policy/security assessment."""

    schema_version: Literal["ocr-handoff-v1"] = "ocr-handoff-v1"
    observation_id: str
    document_hashes: list[Digest] = Field(min_length=1, max_length=2)
    extraction_version: Literal["spatial-rules-v2"] = "spatial-rules-v2"
    graph_rule_version: Literal["graph-rules-v2"] = "graph-rules-v2"
    comparison_version: Literal["invoice-po-rules-v3"] = "invoice-po-rules-v3"
    review_required: bool
    review_reasons: list[str] = Field(default_factory=list, max_length=100)
    injection_flags: list[str] = Field(default_factory=list, max_length=100)
    fraud_codes: list[str] = Field(default_factory=list, max_length=100)
    fraud_score: float = Field(ge=0, le=1)
    score_semantics: Literal["uncalibrated_rule_aggregation"] = "uncalibrated_rule_aggregation"
    financial_authority: Literal[False] = False
    bank_ownership_verified: Literal[False] = False
    authenticity: Literal["unsigned_service_response"] = "unsigned_service_response"
    registry_fingerprint_version: Literal["v1"] = "v1"
    local_fingerprint_version: Literal["v2"] = "v2"
    bank_token_version: Literal["v2"] = "v2"
    required_consumer_checks: tuple[str, ...] = (
        "authenticate_service_response",
        "bind_document_hashes_to_request",
        "enforce_review_and_injection_rules",
        "respect_unknown_line_unit_checks",
        "check_registry_and_po_allocation",
        "verify_payee_and_wallet_mandate",
    )


class InvoicePoVerificationResult(LocalModel):
    schema_version: Literal["ocr-local-v1"] = "ocr-local-v1"
    status: Literal["matched", "review", "mismatch"]
    invoice: DocumentExtraction
    purchase_order: DocumentExtraction
    compatible_invoice: ExtractedInvoice | None = None
    checks: list[ComparisonCheck] = Field(default_factory=list, max_length=1000)
    review_reasons: list[str] = Field(default_factory=list, max_length=100)
    fraud_details: list[FraudFinding] = Field(default_factory=list, max_length=1000)
    fraud_graph: FraudGraph | None = None
    handoff: ConsumerHandoff | None = None

    @model_validator(mode="after")
    def validate_pair(self) -> InvoicePoVerificationResult:
        if self.invoice.document_type != "invoice" or self.purchase_order.document_type != "purchase_order":
            raise ValueError("Verification requires an invoice and a purchase order")
        has_mismatch = any(check.status == "mismatch" for check in self.checks)
        if has_mismatch and self.status != "mismatch":
            raise ValueError("Resolved mismatches cannot be downgraded")
        if (
            self.status != "matched"
            and self.compatible_invoice
            and self.compatible_invoice.confidence >= REVIEW_CONFIDENCE
        ):
            raise ValueError("Unmatched projections must require consumer review")
        if self.handoff:
            if self.handoff.document_hashes != [self.invoice.doc_hash, self.purchase_order.doc_hash]:
                raise ValueError("Handoff must bind both uploaded documents")
            if self.handoff.review_required != (self.status != "matched"):
                raise ValueError("Handoff review must agree with pair status")
            if self.compatible_invoice and self.handoff.observation_id != self.compatible_invoice.invoice_id:
                raise ValueError("Handoff observation must agree with compatible invoice")
        invoice_refs = {ref.ref_id for ref in self.invoice.evidence}
        po_refs = {ref.ref_id for ref in self.purchase_order.evidence}
        for check in self.checks:
            if not set(check.invoice_evidence_refs) <= invoice_refs:
                raise ValueError("Comparison invoice reference is unresolved")
            if not set(check.po_evidence_refs) <= po_refs:
                raise ValueError("Comparison PO reference is unresolved")
        required_checks = {
            "po_reference",
            "supplier.identity",
            "buyer.identity",
            "currency",
            "tax_basis",
            "subtotal",
            "tax_amount",
            "amount",
        }
        if self.status == "matched" and (
            not required_checks <= {check.field for check in self.checks}
            or not any(check.field.endswith(".quantity") for check in self.checks)
            or any(check.status != "match" for check in self.checks)
            or self.review_reasons
            or self.invoice.review_reasons
            or self.purchase_order.review_reasons
        ):
            raise ValueError("Matched pairs require resolved checks and no review reasons")
        return self
