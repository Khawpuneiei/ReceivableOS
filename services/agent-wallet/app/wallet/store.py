"""Off-chain wallet state: idempotency results, receivable facts, pending approvals (CLAUDE.md 5.5)."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from shared.schemas import WalletResult


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


class Store:
    def __init__(self) -> None:
        self.results: dict[str, WalletResult] = {}  # idempotency_key -> first result
        self.receivables: dict[str, ReceivableFact] = {}  # invoice_fingerprint -> fact
        self.pending: dict[str, int] = {}  # wallet tx_id -> ledger pending id
        self.spends: list[tuple[datetime, Decimal]] = []  # draws and pending draws, for the 24h cap
