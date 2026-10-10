"""Shared API contract for ReceivableOS services.

This file is the source of truth for what the services send each other.
Owner: PM. Change it only through a dedicated `contract:` PR (see CLAUDE.md).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    amount: Decimal


class ExtractedInvoice(BaseModel):
    """Response of POST /ocr/extract."""

    invoice_id: str
    supplier: str
    buyer: str
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


class Decision(str, Enum):
    approve = "approve"
    review = "review"
    reject = "reject"


class PolicyRequest(BaseModel):
    """Body of POST /policy/decide."""

    invoice: ExtractedInvoice
    supplier_profile: dict[str, Any] = {}
    buyer_profile: dict[str, Any] = {}


class PolicyDecision(BaseModel):
    """Response of POST /policy/decide."""

    decision: Decision
    advance_rate: float = Field(ge=0, le=1)
    limit: Decimal
    fee_rate: float = Field(ge=0)
    risk_score: float = Field(ge=0, le=1)
    reasons: list[str] = []


class WalletRequest(BaseModel):
    """Body of POST /wallet/execute."""

    decision: PolicyDecision
    payee: str
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)
    invoice_id: str


class TxStatus(str, Enum):
    executed = "executed"
    pending_approval = "pending_approval"
    rejected = "rejected"


class WalletResult(BaseModel):
    """Response of POST /wallet/execute."""

    tx_id: str
    status: TxStatus
    chain_ref: str | None = None
    approvals_required: int = 0
    audit_ref: str
