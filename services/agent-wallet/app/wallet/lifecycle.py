"""Wallet lifecycle: API requests -> guard -> ledger (CLAUDE.md 5.5, 6). Owner: Agent AI engineer.

Idempotency: a repeated write with the same key returns the stored result and sends nothing to the ledger.
Off-chain checks run before any ledger call; the ledger's own checks run again on chain, so a compromised
service still cannot pay outside the mandate.
"""

import hashlib
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ledger.base import ChainResult, LedgerAdapter
from pydantic import ValidationError

from app.audit.log import AuditLog
from app.guard.injection import Classifier, scan_payload
from app.guard.pipeline import GuardContext, check_draw
from app.models import (
    ApproveIntent,
    DrawIntent,
    Mandate,
    Payee,
    RegisterIntent,
    SettleIntent,
)
from app.money import apr_to_bps
from app.wallet.store import ReceivableFact, Store
from shared.money import fee_rate_30d_to_apr
from shared.schemas import (
    GuardCheck,
    TxStatus,
    WalletApproveRequest,
    WalletRegisterRequest,
    WalletRequest,
    WalletResult,
    WalletSettleRequest,
)

CENT = Decimal("0.01")
BANGKOK = timezone(timedelta(hours=7))
TARGET_NAMES = {"ReceivableRegistry": "Registry", "FinancingVault": "Vault"}  # mandate name -> ledger name
ZERO_ADDRESS = "0x" + "00" * 20  # placeholder for an unresolved payee; the guard always blocks it


class WalletService:
    def __init__(
        self,
        ledger: LedgerAdapter,
        store: Store,
        payees: dict[str, Payee],
        platform_fee_rate: Decimal,
        clock: Callable[[], datetime],
        demo_mode: bool = False,
        canary: str | None = None,
        classifier: Classifier | None = None,
    ) -> None:
        self.ledger = ledger
        self.store = store
        self.payees = payees
        self.platform_fee_rate = platform_fee_rate
        self.clock = clock
        self.demo_mode = demo_mode
        self.canary = canary
        self.classifier = classifier
        self.mandate: Mandate | None = None
        self.paused = False
        self.audit = AuditLog()

    # ----- helpers -----

    def _today(self):
        return self.clock().astimezone(BANGKOK).date()

    def _payee_address(self, payee: str) -> str | None:
        """Registry id -> address. A raw address is accepted only if it is a registry address."""
        if payee in self.payees:
            return self.payees[payee].address
        return next((p.address for p in self.payees.values() if p.address.lower() == payee.lower()), None)

    def _default_seller_id(self) -> str | None:
        return next((k for k in self.payees if k.startswith("SELLER:")), None)

    @staticmethod
    def _offchain_block(code: str, layer: str) -> WalletResult:
        tx_id = f"tx_{uuid.uuid4().hex[:16]}"
        return WalletResult(
            tx_id=tx_id,
            status=TxStatus.blocked,
            audit_ref=f"aud_{tx_id[3:15]}",
            block_reason=code,
            checks=[GuardCheck(layer=layer, code=code, passed=False)],
        )

    @staticmethod
    def _blocked(checks: list[GuardCheck]) -> WalletResult:
        """Off-chain block: the first failing check in layer order is the reason. No ledger call was made."""
        tx_id = f"tx_{uuid.uuid4().hex[:16]}"
        first = next((c.code for c in checks if not c.passed), None)
        return WalletResult(
            tx_id=tx_id,
            status=TxStatus.blocked,
            audit_ref=f"aud_{tx_id[3:15]}",
            block_reason=first,
            checks=checks,
        )

    def _scan_blocks(self, request: Any) -> WalletResult | None:
        """L2 for requests without a draw: an injection or canary in any string blocks the call."""
        report = scan_payload(request.model_dump(mode="json"), self.canary, self.classifier)
        if report.canary_hit:
            return self._blocked([GuardCheck(layer="L2", code="CanaryLeak", passed=False)])
        if report.injection_flagged:
            return self._blocked([GuardCheck(layer="L2", code="InjectionSuspected", passed=False)])
        return None

    def _spent_24h(self) -> Decimal:
        cutoff = self.clock() - timedelta(hours=24)
        return sum((amount for at, amount in self.store.spends if at >= cutoff), Decimal(0))

    def _context(self) -> GuardContext:
        return GuardContext(
            now=self.clock(),
            mandate=self.mandate,
            paused=self.paused,
            spent_last_24h=self._spent_24h(),
            canary=self.canary,
            classifier=self.classifier,
        )

    def _finish(self, res: ChainResult, extra: list[GuardCheck] | None = None) -> WalletResult:
        """Maps a ledger result to the API result (CLAUDE.md 6.2)."""
        tx_id = f"tx_{uuid.uuid4().hex[:16]}"
        common = {
            "tx_id": tx_id,
            "audit_ref": f"aud_{tx_id[3:15]}",
            "chain": self.ledger.name,
            "chain_ref": res.tx_hash,
        }
        checks = list(extra or [])
        if res.pending_id is not None:
            self.store.pending[tx_id] = res.pending_id
            checks.append(GuardCheck(layer="L4", code="NeedsHumanApproval", passed=False))
            return WalletResult(
                status=TxStatus.pending_approval, approvals_required=1, checks=checks, **common
            )
        if res.ok:
            return WalletResult(status=TxStatus.executed, checks=checks, **common)
        code = res.revert_reason or "Unknown"
        checks.append(GuardCheck(layer="L5", code=code, passed=False))
        return WalletResult(status=TxStatus.blocked, block_reason=code, checks=checks, **common)

    def _run(self, action: str, invoice_id: str, key: str, run: Callable[[], WalletResult]) -> WalletResult:
        """Idempotent write. A repeat returns the stored result, sends nothing, and is audited."""
        if key in self.store.results:
            stored = self.store.results[key]
            replay = GuardCheck(layer="IDEM", code="IdempotentReplay", passed=True)
            result = stored.model_copy(update={"checks": [*stored.checks, replay]})
            self._audit(invoice_id, action, result, event="REPLAY")
            return result
        result = run()
        self.store.results[key] = result
        self._audit(invoice_id, action, result)
        return result

    def _audit(
        self,
        invoice_id: str,
        action: str,
        result: WalletResult,
        event: str | None = None,
        actor: str = "agent",
    ) -> None:
        """One CHECK entry per guard check, then the outcome. A settlement is anchored on chain afterwards."""
        self.store.txs[result.tx_id] = (invoice_id, result)
        ref = result.audit_ref
        if event is None:
            for check in result.checks:
                data = {"layer": check.layer, "code": check.code, "passed": check.passed}
                self.audit.record(
                    invoice_id=invoice_id,
                    audit_ref=ref,
                    action=action,
                    event="CHECK",
                    actor=actor,
                    tx_id=result.tx_id,
                    data=data,
                )
            outcome = {TxStatus.executed: "EXECUTED", TxStatus.blocked: "BLOCKED"}
            event = outcome.get(result.status, "NEEDS_APPROVAL")
        data = {"block_reason": result.block_reason, "chain": result.chain, "chain_ref": result.chain_ref}
        self.audit.record(
            invoice_id=invoice_id,
            audit_ref=ref,
            action=action,
            event=event,
            actor=actor,
            tx_id=result.tx_id,
            data=data,
        )
        if action == "settle" and result.status == TxStatus.executed:
            head = self.audit.head
            anchor = self.ledger.anchor_audit(head, len(self.audit.entries))
            self.audit.record(
                invoice_id=invoice_id,
                audit_ref=ref,
                action="anchor",
                event="ANCHORED",
                actor=actor,
                tx_id=result.tx_id,
                data={"head": head, "entries": len(self.audit.entries), "chain_ref": anchor.tx_hash},
            )

    def _invoice_of(self, fingerprint: str) -> str:
        fact = self.store.receivables.get(fingerprint)
        return fact.invoice_id if fact else fingerprint

    @staticmethod
    def _default_key(fingerprint: str, action: str) -> str:
        return hashlib.sha256(f"{fingerprint}:{action}".encode()).hexdigest()

    # ----- TX-1: register -----

    def register(self, req: WalletRegisterRequest) -> WalletResult:
        key = req.idempotency_key
        return self._run("register", req.invoice_id, key, lambda: self._register(req))

    def _register(self, req: WalletRegisterRequest) -> WalletResult:
        seller_id = req.seller or self._default_seller_id() or ""
        seller = self._payee_address(seller_id)
        if seller is None:
            return self._offchain_block("PayeeNotAllowed", "L3")
        try:
            intent = RegisterIntent(
                invoice_id=req.invoice_id,
                invoice_fingerprint=req.invoice_fingerprint,
                doc_hash=req.doc_hash,
                face_value=req.face_value,
                currency=req.currency,
                due_date=req.due_date,
                seller_id=seller_id,
                seller_address=seller,
            )
        except ValidationError:
            return self._offchain_block("SchemaInvalid", "L0")
        if (blocked := self._scan_blocks(req)) is not None:
            return blocked
        res = self.ledger.register(intent)
        if res.ok:
            self.store.receivables[req.invoice_fingerprint] = ReceivableFact(
                invoice_id=req.invoice_id,
                seller_id=seller_id,
                seller_address=seller,
                face_value=req.face_value,
                due_date=req.due_date,
            )
        return self._finish(res)

    # ----- TX-2: credit approval (risk oracle) -----

    def approve(self, req: WalletApproveRequest) -> WalletResult:
        key = req.idempotency_key
        invoice_id = self._invoice_of(req.invoice_fingerprint)
        return self._run("approve", invoice_id, key, lambda: self._approve(req))

    def _approve(self, req: WalletApproveRequest) -> WalletResult:
        max_apr_bps = apr_to_bps(fee_rate_30d_to_apr(req.fee_rate))
        try:
            intent = ApproveIntent(
                invoice_fingerprint=req.invoice_fingerprint,
                limit=req.limit,
                max_apr_bps=max_apr_bps,
                decision_hash=req.decision_hash,
            )
        except ValidationError:
            return self._offchain_block("SchemaInvalid", "L0")
        if (blocked := self._scan_blocks(req)) is not None:
            return blocked
        res = self.ledger.approve(intent)
        fact = self.store.receivables.get(req.invoice_fingerprint)
        if res.ok and fact is not None:
            fact.limit, fact.fee_rate, fact.decision_hash = req.limit, req.fee_rate, req.decision_hash
        return self._finish(res)

    # ----- TX-4: draw -----

    def execute(self, req: WalletRequest) -> WalletResult:
        fingerprint = req.invoice_fingerprint or ""
        key = req.idempotency_key or self._default_key(fingerprint, "draw")
        return self._run("draw", req.invoice_id, key, lambda: self._execute(req, fingerprint))

    def _execute(self, req: WalletRequest, fingerprint: str) -> WalletResult:
        resolved = self._payee_address(req.payee)
        # An unresolved payee still goes through the guard, so the decision-level codes are reported too.
        payee_address = resolved or ZERO_ADDRESS
        fact = self.store.receivables.get(fingerprint)
        # Fail closed: the highest APR any source claims. The fee-derived APR is always present.
        claimed = [
            v
            for v in (req.apr, req.decision.apr, fee_rate_30d_to_apr(req.decision.fee_rate))
            if v is not None
        ]
        apr = max(claimed)
        tenor_days = max(0, (fact.due_date - self._today()).days) if fact else 0  # past due: no lender fee
        lender_fee = (req.amount * req.decision.fee_rate * tenor_days / 30).quantize(CENT, ROUND_HALF_UP)
        face = fact.face_value if fact else Decimal(0)
        platform_fee = (face * self.platform_fee_rate).quantize(CENT, ROUND_HALF_UP)
        try:
            intent = DrawIntent(
                invoice_id=req.invoice_id,
                invoice_fingerprint=fingerprint,
                mandate_id=req.mandate_id or (self.mandate.mandate_id if self.mandate else ""),
                lender_id=req.lender_id or "",
                payee_id=req.payee,
                payee_address=payee_address,
                amount=req.amount,
                apr_bps=apr_to_bps(apr),
                decision_hash=req.decision_hash or req.decision.decision_hash or "",
                idempotency_key=req.idempotency_key or "",
                lender_fee=lender_fee,
                platform_fee=platform_fee,
            )
        except ValidationError:
            return self._offchain_block("SchemaInvalid", "L0")
        if req.skip_offchain_checks and self.demo_mode:  # DEMO_MODE only: the chain alone has to refuse
            guard_checks = [GuardCheck(layer="DEMO", code="OffchainBypassed", passed=True)]
        else:
            guard = check_draw(intent, req, fact, self._context(), payee_resolved=resolved is not None)
            if not guard.passed:
                return self._blocked(guard.checks)
            guard_checks = guard.checks
        res = self.ledger.execute(intent)
        if res.ok and fact is not None:
            fact.drawn_amount = req.amount
        if res.ok or res.pending_id is not None:
            self.store.spends.append((self.clock(), req.amount))
        return self._finish(res, extra=guard_checks)

    # ----- TX-5: settlement waterfall -----

    def settle(self, req: WalletSettleRequest) -> WalletResult:
        key = req.idempotency_key
        return self._run("settle", req.invoice_id, key, lambda: self._settle(req))

    def _settle(self, req: WalletSettleRequest) -> WalletResult:
        try:
            intent = SettleIntent(
                invoice_id=req.invoice_id,
                invoice_fingerprint=req.invoice_fingerprint,
                amount_paid=req.amount_paid,
                paid_at=req.paid_at,
            )
        except ValidationError:
            return self._offchain_block("SchemaInvalid", "L0")
        if (blocked := self._scan_blocks(req)) is not None:
            return blocked
        res = self.ledger.settle(intent)
        flags: list[GuardCheck] = []
        fact = self.store.receivables.get(req.invoice_fingerprint)
        if res.ok and fact is not None:
            principal = fact.drawn_amount or Decimal(0)
            if req.amount_paid < principal:
                flags.append(GuardCheck(layer="FLAG", code="SHORT_PAID", passed=True))
            elif req.amount_paid < fact.face_value:
                flags.append(GuardCheck(layer="FLAG", code="DILUTED", passed=True))
            if req.paid_at is not None and req.paid_at > fact.due_date:
                flags.append(GuardCheck(layer="FLAG", code="LATE", passed=True))
        return self._finish(res, extra=flags)

    # ----- human approval, kill switch, mandate -----

    def confirm(self, tx_id: str, approve: bool) -> WalletResult:
        invoice_id = self.store.txs.get(tx_id, ("unknown", None))[0]
        pending_id = self.store.pending.pop(tx_id, None)
        if pending_id is None:
            result = self._offchain_block("NotPending", "L4")
        elif not approve:
            result = self._offchain_block("ApprovalDeclined", "L4")
        else:
            result = self._finish(self.ledger.confirm(pending_id))
        self._audit(invoice_id, "draw", result, actor="approver")
        return result

    def pause(self, on: bool) -> WalletResult:
        result = self._finish(self.ledger.pause(on))
        if result.status == TxStatus.executed:
            self.paused = on
        self._audit("wallet", "pause" if on else "unpause", result, actor="operator")
        return result

    def activate_mandate(self, mandate_dict: dict, max_tx: Decimal, daily_cap: Decimal) -> Mandate:
        """Validate a compiled mandate and write it on chain. ValueError means out of bounds (HTTP 422)."""
        mandate = Mandate.model_validate(mandate_dict)
        mandate.within_ceilings(max_tx, daily_cap)
        missing = [p for p in mandate.payee_allowlist if p not in self.payees]
        if missing:
            raise ValueError(f"payees not in the registry: {missing}")
        addresses = [self.payees[p].address for p in mandate.payee_allowlist]
        targets = [TARGET_NAMES[t] for t in mandate.allowed_targets if t in TARGET_NAMES]
        res = self.ledger.set_mandate(mandate, addresses, targets)
        if not res.ok:
            raise ValueError(res.revert_reason or "set_mandate failed")
        self.mandate = mandate
        return mandate
