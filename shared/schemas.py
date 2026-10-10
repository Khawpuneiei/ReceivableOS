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
    invoice_fingerprint: str  # "sha256:<hex>" of canonical content; the registry's duplicate key


class Decision(str, Enum):
    approve = "approve"
    review = "review"
    reject = "reject"


class PolicyRequest(BaseModel):
    """Body of POST /policy/decide (scope 4.2)."""

    invoice: ExtractedInvoice
    supplier_profile: dict[str, Any] = {}
    buyer_profile: dict[str, Any] = {}


class PolicyDecision(BaseModel):
    """Response of POST /policy/decide (scope 4.2)."""

    decision: Decision
    advance_rate: Decimal = Field(ge=0, le=1)
    limit: Decimal
    fee_rate: Decimal = Field(ge=0)
    risk_score: float = Field(ge=0, le=1)
    reasons: list[str] = []
    model_version: str
    policy_version: str


class WalletRequest(BaseModel):
    """Body of POST /wallet/execute (scope 4.3)."""

    decision: PolicyDecision
    payee: str
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)
    invoice_id: str


class TxStatus(str, Enum):
    executed = "executed"
    blocked = "blocked"
    pending_approval = "pending_approval"
    failed = "failed"


class WalletResult(BaseModel):
    """Response of POST /wallet/execute (scope 4.3)."""

    tx_id: str
    status: TxStatus
    chain_ref: str | None = None  # FISCO BCOS tx hash, or "mock:..."
    approvals_required: int = 0
    audit_ref: str
