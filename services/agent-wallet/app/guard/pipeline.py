"""Off-chain guard pipeline L0-L4 for a draw (CLAUDE.md 5.4). Owner: Agent AI engineer.

Every check runs and every failure is reported. The block reason is the first failing code in layer order.
If any blocking check fails, nothing is sent to the ledger. The ledger repeats the money checks on chain, so a
compromised service still cannot pay outside the mandate. L4 escalates; it does not block.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.guard.injection import Classifier, scan_payload
from app.models import DrawIntent, GuardResult, Mandate, canonical_hash, intent_hash
from app.money import apr_to_bps
from app.wallet.store import ReceivableFact
from shared.money import fee_rate_30d_to_apr
from shared.schemas import Decision as DecisionKind
from shared.schemas import GuardCheck, WalletRequest

BPS = Decimal(10_000)


@dataclass(frozen=True)
class GuardContext:
    now: datetime
    mandate: Mandate | None
    paused: bool
    spent_last_24h: Decimal
    canary: str | None = None
    classifier: Classifier | None = None
    classifier_action: str = "log"  # "log" audits flags, "hold" routes them to a human, "block" rejects


def check_draw(
    intent: DrawIntent,
    req: WalletRequest,
    fact: ReceivableFact | None,
    ctx: GuardContext,
    payee_resolved: bool = True,
) -> GuardResult:
    checks: list[GuardCheck] = []

    def add(layer: str, code: str, ok: bool) -> None:
        checks.append(GuardCheck(layer=layer, code=code, passed=bool(ok)))

    m = ctx.mandate
    decision = req.decision
    add("L0", "CurrencyNotAllowed", m is None or req.currency == m.allowed_currency)

    # L1: decision provenance. The decision must be approve, and its hash must be the one approved on chain.
    # No credit approval (TX-2) on an existing receivable is also NotApproved; for an unknown invoice the
    # missing-receivable code is reported instead.
    approved_by_oracle = fact is None or fact.limit is not None
    add("L1", "NotApproved", decision.decision == DecisionKind.approve and approved_by_oracle)
    recomputed = canonical_hash(decision.model_dump(mode="json", exclude={"decision_hash", "valid_until"}))
    valid_until = getattr(decision, "valid_until", None)
    add("L1", "DecisionStale", valid_until is None or ctx.now <= valid_until)
    approved_hash = fact.decision_hash.lower() if fact and fact.decision_hash else None
    tampered = recomputed != intent.decision_hash.lower() or (
        approved_hash is not None and approved_hash != intent.decision_hash.lower()
    )
    add("L1", "DecisionTampered", not tampered)

    # L2: untrusted text. Injection rules first, then the canary.
    report = scan_payload(req.model_dump(mode="json"), ctx.canary, ctx.classifier)
    add("L2", "CanaryLeak", not report.canary_hit)  # a leaked canary is the strongest signal: report it first
    blocking = report.rule_flagged or (report.classifier_flagged and ctx.classifier_action == "block")
    add("L2", "InjectionSuspected", not blocking)
    if report.classifier_flagged and ctx.classifier_action == "hold":
        checks.append(GuardCheck(layer="HOLD", code="InjectionSuspected", passed=False))
    elif report.classifier_flagged and ctx.classifier_action == "log":
        checks.append(GuardCheck(layer="L2", code="ClassifierFlag", passed=True))

    # L3: mandate and spending. Needs a registered receivable.
    add("L3", "NotRegistered", fact is not None)
    add(
        "L3",
        "PayeeNotAllowed",
        payee_resolved and (fact is None or intent.payee_address.lower() == fact.seller_address.lower()),
    )
    if fact is not None:
        add("L3", "PayeeNotAllowed", intent.payee_address.lower() == fact.seller_address.lower())
        add("L3", "AlreadyDrawn", fact.drawn_amount is None)
        add("L3", "Paused", not ctx.paused)
        amount = intent.amount
        approved_apr_bps = apr_to_bps(fee_rate_30d_to_apr(fact.fee_rate)) if fact.fee_rate is not None else 0
        if m is not None:
            add("L3", "MandateNotYetValid", ctx.now >= m.valid_from)
            add("L3", "MandateExpired", m.expires_at is None or ctx.now < m.expires_at)
            add("L3", "MandateMismatch", req.mandate_id is None or req.mandate_id == m.mandate_id)
            mandate_apr_bps = int(m.max_apr * BPS)
            add("L3", "AprAboveMandate", intent.apr_bps <= min(mandate_apr_bps, approved_apr_bps))
            add("L3", "AmountAboveTxCap", amount <= m.max_amount_per_tx)
            add("L3", "DailyCapExceeded", ctx.spent_last_24h + amount <= m.daily_cap)
            add("L3", "PdAboveMandate", Decimal(str(decision.risk_score)) <= m.max_predicted_default)
        if m is not None:
            add("L3", "AdvanceAboveMandate", decision.advance_rate <= m.max_ltv)  # the rate the lender offers
        approved_limit = fact.limit if fact.limit is not None else Decimal(0)
        add("L3", "AmountAboveLimit", amount <= decision.limit and amount <= approved_limit)
        if m is not None:
            add("L3", "AdvanceAboveMandate", amount <= fact.face_value * m.max_ltv)  # the money, against face

    # L4: escalation. Amount at or above the threshold waits for the approver (inclusive).
    needs_approval = m is not None and intent.amount >= m.human_review_above
    return GuardResult(intent_hash=intent_hash(intent), checks=checks, needs_approval=needs_approval)
