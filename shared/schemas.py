"""Shared API contract for ReceivableOS services.

Mirrors section 4 of docs/00-scope.md. That section is the spec; this file is its code.
Owner: PM. To change it, edit docs/00-scope.md section 4 first in a `contract:` PR (see CLAUDE.md).

Money and rates are Decimal, which Pydantic serialises as JSON strings ("10000.00").
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Party(BaseModel):
    name: str
    tax_id: str | None = None


class LineItem(BaseModel):
    description: str
    qty: Decimal = Decimal("1")
    unit_price: Decimal
    total: Decimal


class ExtractedInvoice(BaseModel):
    """Response of POST /ocr/extract (scope 4.1)."""

    invoice_id: str
    supplier: Party
    buyer: Party
    invoice_no: str
    issue_date: date
    due_date: date
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)
    line_items: list[LineItem] = []
    confidence: float = Field(ge=0, le=1)
    injection_flags: list[str] = []
    fraud_score: float = Field(ge=0, le=1)
    fraud_flags: list[str] = []
    doc_hash: str  # "sha256:<hex of file bytes>"; changes if the file is re-saved
    # "0x" + HMAC-SHA256 hex of the canonical content, key FINGERPRINT_HMAC_KEY; registry key (bytes32)
    invoice_fingerprint: str


class Decision(str, Enum):
    approve = "approve"
    review = "review"
    reject = "reject"


class PolicyRequest(BaseModel):
    """Body of POST /policy/decide (scope 4.2)."""

    invoice: ExtractedInvoice
    supplier_profile: dict[str, Any] = {}
    buyer_profile: dict[str, Any] = {}


class Reason(BaseModel):
    code: str
    message: str


class PolicyDecision(BaseModel):
    """Response of POST /policy/decide (scope 4.2)."""

    decision: Decision
    advance_rate: Decimal = Field(ge=0, le=1)
    limit: Decimal
    fee_rate: Decimal = Field(ge=0)  # per 30 days
    apr: Decimal | None = Field(default=None, ge=0)  # optional, = shared.money.fee_rate_30d_to_apr(fee_rate)
    risk_score: float = Field(ge=0, le=1)
    reasons: list[str | Reason] = []
    model_version: str
    policy_version: str
    # optional extras (architecture 5.2/5.3, agent-wallet CLAUDE.md 6.2)
    pd: float | None = Field(default=None, ge=0, le=1)
    decision_id: str | None = None
    decision_hash: str | None = None


# --- Agent wallet (scope 4.3; extra endpoints and optional fields from architecture 5.3) ---


class WalletRequest(BaseModel):
    """Body of POST /wallet/execute. The first five fields are the scope contract; the rest are optional."""

    decision: PolicyDecision
    payee: str
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)
    invoice_id: str
    idempotency_key: str | None = None
    decision_id: str | None = None
    decision_hash: str | None = None
    invoice_fingerprint: str | None = None
    doc_hash: str | None = None
    apr: Decimal | None = Field(default=None, ge=0)
    lender_id: str | None = None
    mandate_id: str | None = None
    skip_offchain_checks: bool = False  # honoured only with DEMO_MODE=1, otherwise rejected by the wallet


class WalletRegisterRequest(BaseModel):
    """Body of POST /wallet/register (TX-1). The registry keys on invoice_fingerprint."""

    idempotency_key: str
    invoice_id: str
    invoice_fingerprint: str
    doc_hash: str
    face_value: Decimal
    currency: str = Field(min_length=3, max_length=3)
    due_date: date
    seller: str | None = None  # payee registry id, e.g. "SELLER:siam-fresh-pack"


class WalletApproveRequest(BaseModel):
    """Body of POST /wallet/approve (TX-2): credit approval, signed by the risk-oracle key."""

    idempotency_key: str
    decision_id: str
    decision_hash: str
    invoice_fingerprint: str
    doc_hash: str | None = None
    limit: Decimal
    fee_rate: Decimal
    model_version: str
    policy_version: str
    decision: PolicyDecision | None = None  # lets the wallet recompute decision_hash


class WalletSettleRequest(BaseModel):
    """Body of POST /wallet/settle (TX-5)."""

    idempotency_key: str
    invoice_id: str
    invoice_fingerprint: str
    doc_hash: str | None = None
    amount_paid: Decimal
    paid_at: date | None = None


class MandateActivateRequest(BaseModel):
    """Body of POST /wallet/mandate/activate (owner token). Mandate shape: /policy/mandate/compile."""

    mandate_id: str
    mandate: dict[str, Any]


class WalletConfirmRequest(BaseModel):
    """Body of POST /wallet/confirm/{tx_id}: human approval of a pending_approval tx (owner token)."""

    approve: bool


class TxStatus(str, Enum):
    executed = "executed"
    blocked = "blocked"
    pending_approval = "pending_approval"
    failed = "failed"


class GuardCheck(BaseModel):
    layer: str
    code: str
    passed: bool


class WalletResult(BaseModel):
    """Tx result returned by every wallet write endpoint."""

    tx_id: str
    status: TxStatus
    chain_ref: str | None = None  # FISCO BCOS tx hash, or "mock:..."; present for on-chain reverts too
    approvals_required: int = 0
    audit_ref: str
    schema_version: str = "1"
    chain: str | None = None  # "fisco" or "mock"
    explorer_url: str | None = None
    block_reason: str | None = None  # first blocking guard code, e.g. "AprAboveMandate"
    checks: list[GuardCheck] = []
