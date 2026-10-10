"""In-memory mirror of the five contracts (CLAUDE.md 5.6). Owner: Agent AI engineer.

Same checks, same order and same revert strings as the Solidity code, so CHAIN_MODE=mock answers like FISCO.
Hashes carry the `mock:` prefix so nobody mistakes them for chain hashes. Reverted txs still get a hash,
as they do on chain.

Caller roles (agent, riskOracle, owner, approver) are enforced by the wallet layer before a call reaches here.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.models import ApproveIntent, DrawIntent, Mandate, RegisterIntent, SettleIntent, canonical_json
from ledger.base import ChainResult
from shared.money import to_units

TOKEN_DECIMALS = 2
BPS = 10_000


class MockRevert(Exception):
    """A string revert, the same text as the Solidity require()."""


@dataclass
class _Receivable:
    seller: str
    face: int  # token units
    due: date
    status: str = "registered"  # registered -> approved -> drawn -> settled
    limit: int = 0
    max_apr_bps: int = 0
    principal: int = 0
    paid: int = 0


@dataclass
class _Pending:
    intent: DrawIntent
    lender_fee: int
    platform_fee: int


@dataclass
class MockLedger:
    name: str = "mock"
    clock: Callable[[], datetime] = field(default=lambda: datetime.now().astimezone())
    paused: bool = False
    receivables: dict[str, _Receivable] = field(default_factory=dict)
    payees: set[str] = field(default_factory=set)  # allowlisted addresses (PolicyGuard.setPayee)
    targets: set[str] = field(default_factory=set)  # "Registry", "Vault" (PolicyGuard.setTarget)
    spends: list[tuple[datetime, int]] = field(default_factory=list)  # rolling 24h, counts pending too
    pending: dict[int, _Pending] = field(default_factory=dict)
    balances: dict[str, int] = field(default_factory=dict)  # token units per party
    anchors: list[tuple[str, int]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    _mandate: Mandate | None = None
    _prev_hash: str = "0x" + "00" * 32
    _next_pending: int = 1
    _block: int = 0

    # ----- state helpers -----

    def _hash(self, payload: dict[str, Any]) -> str:
        digest = hashlib.sha256((self._prev_hash + canonical_json(payload)).encode()).hexdigest()
        self._prev_hash = "0x" + digest
        return "mock:0x" + digest

    def _credit(self, party: str, units: int) -> None:
        self.balances[party] = self.balances.get(party, 0) + units

    def _debit(self, party: str, units: int) -> None:
        self.balances[party] = self.balances.get(party, 0) - units

    def _receivable(self, fp: str) -> _Receivable:
        r = self.receivables.get(fp)
        if r is None:
            raise MockRevert("NotRegistered")
        return r

    def _rolling_spend(self) -> int:
        cutoff = self.clock().timestamp() - 86_400
        self.spends = [(t, a) for t, a in self.spends if t.timestamp() >= cutoff]
        return sum(a for _, a in self.spends)

    def _mandate_or_revert(self) -> Mandate:
        if self._mandate is None:
            raise MockRevert("MandateNotSet")
        return self._mandate

    def _tx(self, name: str, payload: dict[str, Any], op: Callable[[], dict[str, Any]]) -> ChainResult:
        self._block += 1
        try:
            events = op()
        except MockRevert as revert:
            tx_hash = self._hash({"action": name, "payload": payload, "reverted": str(revert)})
            return ChainResult(ok=False, tx_hash=tx_hash, block_number=self._block, revert_reason=str(revert))
        tx_hash = self._hash({"action": name, "payload": payload, "events": events})
        self.events.append({"tx_hash": tx_hash, "action": name, **events})
        return ChainResult(
            ok=True,
            tx_hash=tx_hash,
            block_number=self._block,
            events=events,
            pending_id=events.get("pending_id"),
        )

    # ----- setup (owner) -----

    def set_mandate(self, mandate: Mandate, payee_addresses: list[str], targets: list[str]) -> ChainResult:
        def op() -> dict[str, Any]:
            self._mandate = mandate
            self.payees = {a.lower() for a in payee_addresses}
            self.targets = set(targets)
            return {"mandate_hash": mandate.mandate_hash}

        return self._tx("setMandate", {"mandate_hash": mandate.mandate_hash}, op)

    def deposit(self, lender: str, amount: Decimal) -> ChainResult:
        units = to_units(amount, TOKEN_DECIMALS)

        def op() -> dict[str, Any]:
            self._debit(lender, units)
            self._credit("vault", units)
            return {"lender": lender, "amount": units}

        return self._tx("deposit", {"lender": lender, "amount": units}, op)

    def pause(self, on: bool) -> ChainResult:
        def op() -> dict[str, Any]:
            self.paused = on
            return {"paused": on}

        return self._tx("pause" if on else "unpause", {"paused": on}, op)

    # ----- TX-1: register (AgentWallet.execute -> Registry.register) -----

    def register(self, r: RegisterIntent) -> ChainResult:
        payload = {"fp": r.invoice_fingerprint, "seller": r.seller_address, "face": str(r.face_value)}

        def op() -> dict[str, Any]:
            if self.paused:
                raise MockRevert("Paused")
            if "Registry" not in self.targets:
                raise MockRevert("TargetNotAllowed")
            if r.seller_address.lower() not in self.payees:
                raise MockRevert("PayeeNotAllowed")
            if r.invoice_fingerprint in self.receivables:
                raise MockRevert("DuplicateReceivable")
            self.receivables[r.invoice_fingerprint] = _Receivable(
                seller=r.seller_address.lower(),
                face=to_units(r.face_value, TOKEN_DECIMALS),
                due=r.due_date,
            )
            return {"fingerprint": r.invoice_fingerprint, "seller": r.seller_address}

        return self._tx("register", payload, op)

    # ----- TX-2: credit approval (riskOracle -> Registry.approve) -----

    def approve(self, a: ApproveIntent) -> ChainResult:
        payload = {"fp": a.invoice_fingerprint, "limit": str(a.limit), "apr_bps": a.max_apr_bps}

        def op() -> dict[str, Any]:
            r = self._receivable(a.invoice_fingerprint)
            if r.status != "registered":
                raise MockRevert("AlreadyApproved")
            r.status = "approved"
            r.limit = to_units(a.limit, TOKEN_DECIMALS)
            r.max_apr_bps = a.max_apr_bps
            return {"fingerprint": a.invoice_fingerprint, "limit": r.limit}

        return self._tx("approve", payload, op)

    # ----- TX-4: draw (AgentWallet.execute -> PolicyGuard.check -> Vault.draw) -----

    def execute(self, d: DrawIntent) -> ChainResult:
        payload = {"fp": d.invoice_fingerprint, "amount": str(d.amount), "apr_bps": d.apr_bps}
        return self._tx("draw", payload, lambda: self._draw(d, confirmed=False))

    def _draw(self, d: DrawIntent, confirmed: bool) -> dict[str, Any]:
        mandate = self._mandate_or_revert()
        if self.paused:
            raise MockRevert("Paused")
        r = self._receivable(d.invoice_fingerprint)
        if d.payee_address.lower() != r.seller:
            raise MockRevert("PayeeNotAllowed")
        if "Vault" not in self.targets:
            raise MockRevert("TargetNotAllowed")
        if mandate.expires_at is not None and self.clock() >= mandate.expires_at:
            raise MockRevert("MandateExpired")
        if r.status == "drawn" or r.status == "settled":
            raise MockRevert("AlreadyDrawn")
        if r.status != "approved":
            raise MockRevert("NotApproved")

        amount = to_units(d.amount, TOKEN_DECIMALS)
        lender_fee = to_units(d.lender_fee, TOKEN_DECIMALS)
        platform_fee = to_units(d.platform_fee, TOKEN_DECIMALS)
        if amount > to_units(mandate.max_amount_per_tx, TOKEN_DECIMALS):
            raise MockRevert("AmountAboveTxCap")
        # A confirmed draw was charged to the daily cap when it was proposed, so it is not counted again.
        if not confirmed and self._rolling_spend() + amount > to_units(mandate.daily_cap, TOKEN_DECIMALS):
            raise MockRevert("DailyCapExceeded")
        if d.apr_bps > int(mandate.max_apr * BPS) or d.apr_bps > r.max_apr_bps:
            raise MockRevert("AprAboveMandate")
        if amount > r.limit:
            raise MockRevert("AmountAboveLimit")
        if amount * BPS > r.face * int(mandate.max_ltv * BPS):
            raise MockRevert("AdvanceAboveMandate")
        if lender_fee + platform_fee >= amount:
            raise MockRevert("FeesExceedAmount")

        threshold = to_units(mandate.human_review_above, TOKEN_DECIMALS)
        if amount >= threshold and not confirmed:
            pending_id = self._next_pending
            self._next_pending += 1
            self.pending[pending_id] = _Pending(d, lender_fee, platform_fee)
            self.spends.append((self.clock(), amount))
            return {"pending_id": pending_id, "needs_approval": True, "amount": amount}

        if not confirmed:
            self.spends.append((self.clock(), amount))
        r.status = "drawn"
        r.principal = amount
        self._debit("vault", amount)
        self._credit(r.seller, amount - lender_fee - platform_fee)
        self._credit("platform", platform_fee)
        self._credit(f"fees:{d.lender_id}", lender_fee)
        return {
            "fingerprint": d.invoice_fingerprint,
            "amount": amount,
            "seller_net": amount - lender_fee - platform_fee,
        }

    # ----- human approval (AgentWallet.confirm, approver) -----

    def confirm(self, pending_id: int) -> ChainResult:
        payload = {"pending_id": pending_id}

        def op() -> dict[str, Any]:
            item = self.pending.get(pending_id)
            if item is None:
                raise MockRevert("NotPending")
            events = self._draw(item.intent, confirmed=True)  # raises -> the pending draw stays queued
            del self.pending[pending_id]
            return events

        return self._tx("confirm", payload, op)

    # ----- TX-5: settle (AgentWallet.execute -> Vault.repay, waterfall) -----

    def settle(self, s: SettleIntent) -> ChainResult:
        payload = {"fp": s.invoice_fingerprint, "paid": str(s.amount_paid)}

        def op() -> dict[str, Any]:
            if self.paused:
                raise MockRevert("Paused")
            r = self._receivable(s.invoice_fingerprint)
            if r.status == "settled":
                raise MockRevert("AlreadySettled")
            if r.status != "drawn":
                raise MockRevert("NotDrawn")
            paid = to_units(s.amount_paid, TOKEN_DECIMALS)
            to_lender = min(paid, r.principal)  # lender principal first
            to_seller = paid - to_lender  # then the seller reserve
            self._credit(f"lender:{s.invoice_fingerprint[:10]}", to_lender)
            self._credit(r.seller, to_seller)
            r.status = "settled"
            r.paid = paid
            return {"fingerprint": s.invoice_fingerprint, "to_lender": to_lender, "to_seller": to_seller}

        return self._tx("settle", payload, op)

    # ----- audit anchor (AgentWallet.anchorAudit) -----

    def anchor_audit(self, root: str, entries: int) -> ChainResult:
        def op() -> dict[str, Any]:
            self.anchors.append((root, entries))
            return {"root": root, "entries": entries}

        return self._tx("anchorAudit", {"root": root, "entries": entries}, op)

    def health(self) -> bool:
        return True
