"""Ledger interface (CLAUDE.md 5.7). Owner: Agent AI engineer.

Every chain call goes through a LedgerAdapter. `mock` and `fisco` implement the same rules and return the same
revert strings, so the guard, lifecycle and tests do not change when CHAIN_MODE changes.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from app.models import ApproveIntent, DrawIntent, Mandate, RegisterIntent, SettleIntent


@dataclass
class ChainResult:
    ok: bool
    tx_hash: str | None = None
    block_number: int | None = None
    revert_reason: str | None = None  # the string revert, e.g. "AprAboveMandate"
    events: dict[str, Any] = field(default_factory=dict)
    pending_id: int | None = None


class LedgerAdapter(Protocol):
    name: str  # "mock" | "fisco"

    def register(
        self, r: RegisterIntent
    ) -> ChainResult: ...  # TX-1: AgentWallet.execute -> Registry.register
    def approve(self, a: ApproveIntent) -> ChainResult: ...  # TX-2: riskOracle -> Registry.approve
    def execute(self, d: DrawIntent) -> ChainResult: ...  # TX-4: AgentWallet.execute -> Vault.draw
    def confirm(self, pending_id: int) -> ChainResult: ...  # approver -> AgentWallet.confirm
    def settle(self, s: SettleIntent) -> ChainResult: ...  # TX-5: AgentWallet.execute -> Vault.repay
    def set_mandate(
        self, mandate: Mandate, payee_addresses: list[str], targets: list[str]
    ) -> ChainResult: ...
    def deposit(self, lender: str, amount: Decimal) -> ChainResult: ...  # TX-3, setup script
    def pause(self, on: bool) -> ChainResult: ...
    def anchor_audit(self, root: str, entries: int) -> ChainResult: ...
    def health(self) -> bool: ...
