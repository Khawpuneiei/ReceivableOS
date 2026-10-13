"""Off-chain wallet state: idempotency results, receivable facts, pending approvals (CLAUDE.md 5.5)."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.models import DrawIntent
from shared.schemas import GuardCheck, WalletRequest, WalletResult


@dataclass
class ReceivableFact:
    invoice_id: str
    seller_id: str
    seller_address: str
    face_value: Decimal
    due_date: date
    fee_rate: Decimal | None = None  # per 30 days, from the approve decision
    limit: Decimal | None = None
    decision_hash: str | None = None
    drawn_amount: Decimal | None = None
    approved_at: datetime | None = None  # when TX-2 succeeded; bounds the decision's age at draw


@dataclass
class Hold:
    """A draft held for an approver. Nothing has been sent to the ledger yet."""

    tx_id: str
    intent: DrawIntent
    request: WalletRequest
    checks: list[GuardCheck]
    held_at: datetime


@dataclass
class ChainPending:
    """A draw the ledger queued for the approver (ApprovalRequired). Kept until the ledger drops it."""

    pending_id: int
    intent: DrawIntent | None
    queued_at: datetime


class Store:
    def __init__(self) -> None:
        self.results: dict[str, WalletResult] = {}  # idempotency_key -> first result
        self.receivables: dict[str, ReceivableFact] = {}  # invoice_fingerprint -> fact
        self.pending: dict[str, ChainPending] = {}  # wallet tx_id -> draw queued on the ledger
        self.spends: list[tuple[datetime, Decimal]] = []  # draws and pending draws, for the 24h cap
        # tx_id -> (invoice_id, result), for GET /wallet/tx
        self.txs: dict[str, tuple[str, WalletResult]] = {}
        self.holds: dict[str, Hold] = {}  # tx_id -> held draft, awaiting an approver
