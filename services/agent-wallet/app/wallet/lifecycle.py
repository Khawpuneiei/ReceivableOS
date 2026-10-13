"""Wallet lifecycle: API requests -> guard -> ledger (CLAUDE.md 5.5, 6). Owner: Agent AI engineer.

Idempotency: a repeated write with the same key returns the stored result and sends nothing to the ledger.
Off-chain checks run before any ledger call; the ledger's own checks run again on chain, so a compromised
service still cannot pay outside the mandate.

Hold path: when the classifier flags a draft and INJECTION_CLASSIFIER_ACTION=hold, the draft is stored and
nothing is sent to the ledger. An approver releases it (every hard check runs again first) or rejects it.
Holds expire after 24 hours, as CLAUDE.md 2.4 requires for pending approvals.

Chain-pending draws (amount at or above the review threshold) follow the same 24 hour rule. The off-chain
record of a queued draw is dropped only when the ledger drops it, so a confirm that reverts (for example while
the wallet is paused) can be retried. A declined or expired draw is declined on the ledger too. While a draw
on a receivable waits for a human, no other draw on it is accepted, so the agent cannot route around the
approver by resubmitting a smaller amount.
"""

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ledger.base import ChainResult, LedgerAdapter
from pydantic import ValidationError

from app.audit.log import AuditLog
from app.guard.injection import Classifier, scan_payload
from app.guard.pipeline import GuardContext, check_draw
from app.guard.signatures import DecisionSigners
from app.guard.tripwire import Tripwire
from app.models import (
    ApproveIntent,
    DrawIntent,
    Mandate,
    Payee,
    RegisterIntent,
    SettleIntent,
    canonical_hash,
    canonical_json,
)
from app.money import apr_to_bps
from app.wallet.store import ChainPending, Hold, ReceivableFact, Store
from shared.money import fee_rate_30d_to_apr
from shared.schemas import Decision as DecisionKind
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
HOLD_TTL = timedelta(hours=24)
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
        classifier_action: str = "log",
        decision_signers: DecisionSigners | None = None,
        tripwire: Tripwire | None = None,
    ) -> None:
        self.ledger = ledger
        self.store = store
        self.payees = payees
        self.platform_fee_rate = platform_fee_rate
        self.clock = clock
        self.demo_mode = demo_mode
        self.canary = canary
        self.classifier = classifier
        self.classifier_action = classifier_action  # "log" | "hold" | "block"
        self.mandate: Mandate | None = None
        self.paused = False
        self.audit = AuditLog()
        self.decision_signers = decision_signers or DecisionSigners()
        self.anchors: list[dict[str, Any]] = []  # Merkle roots written on chain, oldest first
        self.tripwire = tripwire or Tripwire(honeytokens=set(), threshold=0)

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
    def _blocked(checks: list[GuardCheck], reason: str | None = None) -> WalletResult:
        """Off-chain block. The reason is the first hard failure in layer order, never a hold marker."""
        tx_id = f"tx_{uuid.uuid4().hex[:16]}"
        first = reason or next((c.code for c in checks if not c.passed and c.layer != "HOLD"), None)
        return WalletResult(
            tx_id=tx_id,
            status=TxStatus.blocked,
            audit_ref=f"aud_{tx_id[3:15]}",
            block_reason=first,
            checks=checks,
        )

    def _scan_blocks(self, request: Any, exclude: set[str] | None = None) -> WalletResult | None:
        """L2 for requests without a draw. There is no approval path for these, so a hold blocks too.
        `exclude` leaves out fields that are scanned where money moves (the decision, at the draw)."""
        report = scan_payload(request.model_dump(mode="json", exclude=exclude), self.canary, self.classifier)
        if report.canary_hit:
            return self._blocked([GuardCheck(layer="L2", code="CanaryLeak", passed=False)])
        if report.rule_flagged or (report.classifier_flagged and self.classifier_action in ("hold", "block")):
            return self._blocked([GuardCheck(layer="L2", code="InjectionSuspected", passed=False)])
        return None

    def _spent_24h(self) -> Decimal:
        cutoff = self.clock() - timedelta(hours=24)
        return sum((amount for at, amount in self.store.spends if at >= cutoff), Decimal(0))

    def seed_spend(self, amount: Decimal) -> None:
        """Counts what the chain already spent in the last 24h, read at startup. The store is in memory, so
        without this the off-chain cap starts at zero after a restart. The entry is dated now, so the whole
        amount counts for 24h from startup. That is never looser than the chain's sliding window, which the
        chain still enforces exactly."""
        if amount > 0:
            self.store.spends.append((self.clock(), amount))

    def _context(self) -> GuardContext:
        return GuardContext(
            now=self.clock(),
            mandate=self.mandate,
            paused=self.paused,
            spent_last_24h=self._spent_24h(),
            canary=self.canary,
            classifier=self.classifier,
            classifier_action=self.classifier_action,
        )

    def _finish(
        self, res: ChainResult, extra: list[GuardCheck] | None = None, intent: DrawIntent | None = None
    ) -> WalletResult:
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
            self.store.pending[tx_id] = ChainPending(res.pending_id, intent, self.clock())
            checks.append(GuardCheck(layer="L4", code="NeedsHumanApproval", passed=False))
            return WalletResult(
                status=TxStatus.pending_approval, approvals_required=1, checks=checks, **common
            )
        if res.ok:
            return WalletResult(status=TxStatus.executed, checks=checks, **common)
        code = res.revert_reason or "Unknown"
        checks.append(GuardCheck(layer="L5", code=code, passed=False))
        return WalletResult(status=TxStatus.blocked, block_reason=code, checks=checks, **common)

    def _run(
        self,
        action: str,
        invoice_id: str,
        key: str,
        run: Callable[[], WalletResult],
        request: Any = None,
        fingerprint: str = "",
    ) -> WalletResult:
        """Idempotent write. A repeat returns the stored result, sends nothing, and is audited.
        The tripwire runs first (honeytoken, quarantine) and learns from every blocked result."""
        if key in self.store.results:
            stored = self.store.results[key]
            replay = GuardCheck(layer="IDEM", code="IdempotentReplay", passed=True)
            result = stored.model_copy(update={"checks": [*stored.checks, replay]})
            self._audit(invoice_id, action, result, event="REPLAY")
            return result
        if self.tripwire.honeytoken_in(request.model_dump(mode="json") if request else None):
            result = self._offchain_block("HoneytokenTouched", "TRIP")
        elif action != "settle" and self.tripwire.is_quarantined(fingerprint):  # repayment is never held
            result = self._offchain_block("InvoiceQuarantined", "TRIP")
        else:
            result = run()
        self.store.results[key] = result
        self._audit(invoice_id, action, result)
        if result.status == TxStatus.blocked:
            codes = {result.block_reason} | {c.code for c in result.checks if not c.passed}
            if self.tripwire.observe(self.clock(), fingerprint, {c for c in codes if c}) and not self.paused:
                self.pause(True, actor="tripwire")
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
            self.anchor_audit(invoice_id, actor, result.tx_id, ref)

    def anchor_audit(
        self, invoice_id: str = "wallet", actor: str = "agent", tx_id: str | None = None, ref: str = ""
    ) -> dict[str, Any]:
        """Writes the Merkle root of the log so far on chain, then records that it did. The ANCHORED entry
        itself falls in the next anchor, so every entry is eventually covered."""
        size = len(self.audit.entries)
        root, head = self.audit.merkle_root(size), self.audit.head
        res = self.ledger.anchor_audit(root, size)
        anchor = {"root": root, "entries": size, "head": head, "chain_ref": res.tx_hash, "ok": res.ok}
        if res.ok:
            self.anchors.append(anchor)
        self.audit.record(
            invoice_id=invoice_id,
            audit_ref=ref or f"anc_{size}",
            action="anchor",
            event="ANCHORED" if res.ok else "ANCHOR_FAILED",
            actor=actor,
            tx_id=tx_id,
            data=anchor,
        )
        return anchor

    def audit_proof(self, seq: int) -> dict[str, Any]:
        """Inclusion proof for entry `seq` against the first anchor that covers it, or against the current
        root (anchored: False) when no anchor covers it yet. KeyError when there is no such entry."""
        if not 1 <= seq <= len(self.audit.entries):
            raise KeyError(seq)
        anchor = next((a for a in self.anchors if a["entries"] >= seq), None)
        size = anchor["entries"] if anchor else len(self.audit.entries)
        entry = self.audit.entries[seq - 1]
        return {
            "entry": entry,
            "leaf_index": seq - 1,
            "tree_size": size,
            "proof": self.audit.inclusion_proof(seq, size),
            "root": anchor["root"] if anchor else self.audit.merkle_root(size),
            "anchored": anchor is not None,
            "chain_ref": anchor["chain_ref"] if anchor else None,
        }

    def _invoice_of(self, fingerprint: str) -> str:
        fact = self.store.receivables.get(fingerprint)
        return fact.invoice_id if fact else fingerprint

    @staticmethod
    def _request_key(req: WalletRequest) -> str:
        """Default key for a draw sent without one: a hash of the whole body.
        A different draw never shares it, so a retry replays only the identical request."""
        body = req.model_dump(mode="json", exclude={"idempotency_key"})
        return hashlib.sha256(canonical_json(body).encode()).hexdigest()

    # ----- TX-1: register -----

    def register(self, req: WalletRegisterRequest) -> WalletResult:
        key = req.idempotency_key
        return self._run(
            "register", req.invoice_id, key, lambda: self._register(req), req, req.invoice_fingerprint
        )

    def _seller_kyc(self, seller_address: str | None) -> bool:
        """The KYC flag of the payee at this address, while its credential has not expired.
        An address not in the registry, or an expired credential, is not verified."""
        today = self._today()
        return any(
            p.kyc_verified
            and p.address.lower() == (seller_address or "").lower()
            and (p.kyc_expiry is None or today <= p.kyc_expiry)
            for p in self.payees.values()
        )

    def _context_for(self, fact: ReceivableFact | None) -> GuardContext:
        seller_ok = self._seller_kyc(fact.seller_address) if fact else True
        return replace(self._context(), seller_kyc_verified=seller_ok)

    def _register(self, req: WalletRegisterRequest) -> WalletResult:
        seller_id = req.seller or self._default_seller_id() or ""
        seller = self._payee_address(seller_id)
        if seller is None:
            return self._offchain_block("PayeeNotAllowed", "L3")
        if not self._seller_kyc(seller):
            return self._offchain_block("KycNotVerified", "L3")
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

    def approve(self, req: WalletApproveRequest, signature: str | None = None) -> WalletResult:
        key = req.idempotency_key
        invoice_id = self._invoice_of(req.invoice_fingerprint)
        return self._run(
            "approve", invoice_id, key, lambda: self._approve(req, signature), req, req.invoice_fingerprint
        )

    def _approve(self, req: WalletApproveRequest, signature: str | None = None) -> WalletResult:
        # The approval must name an approve decision and match it: the hash covers the decision, and the limit
        # and fee are separate fields, so they are compared with it too.
        decision = req.decision
        if decision is None:
            return self._offchain_block("SchemaInvalid", "L0")
        recomputed = canonical_hash(
            decision.model_dump(mode="json", exclude={"decision_hash", "valid_until"})
        )
        matches = (
            recomputed == req.decision_hash.lower()
            and req.limit == decision.limit
            and req.fee_rate == decision.fee_rate
        )
        checks = [
            GuardCheck(layer="L1", code="NotApproved", passed=decision.decision == DecisionKind.approve),
            GuardCheck(layer="L1", code="DecisionTampered", passed=matches),
        ]
        # The signature is over the decision hash the approval names and the invoice it is for.
        if signature or self.decision_signers.enforce:
            signed = self.decision_signers.check(signature, req.decision_hash, req.invoice_fingerprint)
            checks.append(GuardCheck(layer="L1", code=signed or "DecisionSigned", passed=signed is None))
        if not all(c.passed for c in checks):
            return self._blocked(checks)
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
        if (blocked := self._scan_blocks(req, exclude={"decision"})) is not None:
            return blocked
        res = self.ledger.approve(intent)
        fact = self.store.receivables.get(req.invoice_fingerprint)
        if res.ok and fact is not None:
            fact.limit, fact.fee_rate, fact.decision_hash = req.limit, req.fee_rate, req.decision_hash
        return self._finish(res, extra=[c for c in checks if c.code == "DecisionSigned"])

    # ----- TX-4: draw -----

    def execute(self, req: WalletRequest) -> WalletResult:
        fingerprint = req.invoice_fingerprint or ""
        key = req.idempotency_key or self._request_key(req)
        return self._run(
            "draw", req.invoice_id, key, lambda: self._execute(req, fingerprint), req, fingerprint
        )

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
        elif self._awaiting_approval(req.invoice_fingerprint):
            return self._offchain_block("ApprovalPending", "L4")
        else:
            ctx = self._context_for(fact)
            guard = check_draw(intent, req, fact, ctx, payee_resolved=resolved is not None)
            if any(not c.passed and c.layer != "HOLD" for c in guard.checks):
                return self._blocked(guard.checks)
            if any(not c.passed and c.layer == "HOLD" for c in guard.checks):
                return self._hold(intent, req, guard.checks)  # classifier-only flag: a human decides
            guard_checks = guard.checks
        res = self.ledger.execute(intent)
        if res.ok and res.pending_id is None and fact is not None:  # a queued draw is not drawn yet
            fact.drawn_amount = req.amount
        if res.ok or res.pending_id is not None:
            self.store.spends.append((self.clock(), req.amount))
        return self._finish(res, extra=guard_checks, intent=intent)

    def _hold(self, intent: DrawIntent, req: WalletRequest, checks: list[GuardCheck]) -> WalletResult:
        """Stores the draft and returns pending. The ledger is not called until an approver releases it."""
        tx_id = f"tx_{uuid.uuid4().hex[:16]}"
        self.store.holds[tx_id] = Hold(
            tx_id=tx_id, intent=intent, request=req, checks=checks, held_at=self.clock()
        )
        return WalletResult(
            tx_id=tx_id,
            status=TxStatus.pending_approval,
            approvals_required=1,
            audit_ref=f"aud_{tx_id[3:15]}",
            checks=[*checks, GuardCheck(layer="L4", code="NeedsHumanApproval", passed=False)],
        )

    def _awaiting_approval(self, fingerprint: str) -> bool:
        """True while a draw on this receivable is held or queued on the ledger for the approver."""
        fp = fingerprint.lower()
        held = [h.intent for h in self.store.holds.values()]
        queued = [p.intent for p in self.store.pending.values() if p.intent is not None]
        return any(i.invoice_fingerprint.lower() == fp for i in held + queued)

    def list_holds(self) -> list[dict[str, Any]]:
        """What waits for the approver: ids, amounts and codes only. Invoice text is not shown.

        kind "hold" is a draft the classifier flagged (nothing sent to the ledger); kind "chain_pending" is a
        draw the ledger queued because the amount is at or above the review threshold.
        """
        queued = [
            {
                "kind": "chain_pending",
                "tx_id": tx_id,
                "invoice_id": p.intent.invoice_id if p.intent else None,
                "amount": str(p.intent.amount) if p.intent else None,
                "apr_bps": p.intent.apr_bps if p.intent else None,
                "payee_address": p.intent.payee_address if p.intent else None,
                "held_at": p.queued_at.isoformat(),
                "expires_at": (p.queued_at + HOLD_TTL).isoformat(),
                "flags": ["NeedsHumanApproval"],
            }
            for tx_id, p in self.store.pending.items()
        ]
        return queued + [
            {
                "kind": "hold",
                "tx_id": h.tx_id,
                "invoice_id": h.intent.invoice_id,
                "amount": str(h.intent.amount),
                "apr_bps": h.intent.apr_bps,
                "held_at": h.held_at.isoformat(),
                "expires_at": (h.held_at + HOLD_TTL).isoformat(),
                "flags": sorted({c.code for c in h.checks if not c.passed}),
            }
            for h in self.store.holds.values()
        ]

    def _decide_hold(self, hold: Hold, approve: bool) -> WalletResult:
        if not approve:
            return self._blocked(
                [GuardCheck(layer="L4", code="HoldRejected", passed=False)], reason="HoldRejected"
            )
        if self.clock() - hold.held_at > HOLD_TTL:
            return self._blocked(
                [GuardCheck(layer="L4", code="HoldExpired", passed=False)], reason="HoldExpired"
            )
        # The approver overrides the classifier flag only. Every hard check runs again, because the wallet
        # may have changed (paused, mandate expired, receivable drawn) since the draft was held.
        fact = self.store.receivables.get(hold.intent.invoice_fingerprint)
        ctx = replace(self._context_for(fact), classifier_action="log")
        guard = check_draw(hold.intent, hold.request, fact, ctx, payee_resolved=True)
        if not guard.passed:
            return self._blocked(guard.checks)
        res = self.ledger.execute(hold.intent)
        if res.ok and res.pending_id is None and fact is not None:
            fact.drawn_amount = hold.request.amount
        if res.ok or res.pending_id is not None:
            self.store.spends.append((self.clock(), hold.intent.amount))
        approved = GuardCheck(layer="L4", code="HumanApproved", passed=True)
        return self._finish(res, extra=[*guard.checks, approved], intent=hold.intent)

    # ----- TX-5: settlement waterfall -----

    def settle(self, req: WalletSettleRequest) -> WalletResult:
        key = req.idempotency_key
        return self._run(
            "settle", req.invoice_id, key, lambda: self._settle(req), req, req.invoice_fingerprint
        )

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
        hold = self.store.holds.pop(tx_id, None)
        if hold is not None:
            result = self._decide_hold(hold, approve)
            self._audit(hold.intent.invoice_id, "draw", result, actor="approver")
            return result
        invoice_id = self.store.txs.get(tx_id, ("unknown", None))[0]
        item = self.store.pending.get(tx_id)
        if item is None:
            result = self._offchain_block("NotPending", "L4")
        elif not approve:
            result = self._decline(tx_id, item, "ApprovalDeclined")
        elif self.clock() - item.queued_at > HOLD_TTL:
            result = self._decline(tx_id, item, "ApprovalExpired")
        else:
            res = self.ledger.confirm(item.pending_id)
            if res.ok or res.revert_reason == "NotPending":
                del self.store.pending[tx_id]  # the ledger no longer holds it either
            fact = self.store.receivables.get(item.intent.invoice_fingerprint) if item.intent else None
            if res.ok and fact is not None and item.intent is not None:
                fact.drawn_amount = item.intent.amount
            result = self._finish(res, extra=[GuardCheck(layer="L4", code="HumanApproved", passed=True)])
        self._audit(invoice_id, "draw", result, actor="approver")
        return result

    def _decline(self, tx_id: str, item: ChainPending, code: str) -> WalletResult:
        """Declines the queued draw on the ledger as well, so it cannot be released later."""
        res = self.ledger.confirm(item.pending_id, approve=False)
        if res.ok or res.revert_reason == "NotPending":
            del self.store.pending[tx_id]
        checks = [GuardCheck(layer="L4", code=code, passed=False)]
        if not res.ok and res.revert_reason != "NotPending":  # e.g. Paused: still queued, decline again later
            checks.append(GuardCheck(layer="L5", code=res.revert_reason or "Unknown", passed=False))
        result = self._blocked(checks, reason=code)
        return result.model_copy(update={"chain": self.ledger.name, "chain_ref": res.tx_hash})

    def pause(self, on: bool, actor: str = "operator") -> WalletResult:
        result = self._finish(self.ledger.pause(on))
        if result.status == TxStatus.executed:
            self.paused = on
            if not on:
                self.tripwire.reset()  # the owner unpaused: the breaker re-arms
        self._audit("wallet", "pause" if on else "unpause", result, actor=actor)
        return result

    def activate_mandate(self, mandate_dict: dict, max_tx: Decimal, daily_cap: Decimal) -> Mandate:
        """Validate a compiled mandate and write it on chain. ValueError means out of bounds (HTTP 422)."""
        mandate = Mandate.model_validate(mandate_dict)
        mandate.within_ceilings(max_tx, daily_cap)
        missing = [p for p in mandate.payee_allowlist if p not in self.payees]
        if missing:
            raise ValueError(f"payees not in the registry: {missing}")
        # Only KYC-verified payees go on chain, so an unverified seller cannot be bound on chain either.
        addresses = [self.payees[p].address for p in mandate.payee_allowlist if self.payees[p].kyc_verified]
        targets = [TARGET_NAMES[t] for t in mandate.allowed_targets if t in TARGET_NAMES]
        res = self.ledger.set_mandate(mandate, addresses, targets)
        if not res.ok:
            raise ValueError(res.revert_reason or "set_mandate failed")
        self.mandate = mandate
        return mandate
