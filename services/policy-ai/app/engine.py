"""Credit rule engine (services/policy-ai/CLAUDE.md sections 6.1 and 6.3).

Each rule is a small Python predicate registered under its YAML id; the YAML holds only the parameters,
so no threshold lives here and nothing is ever evaluated as code. Stages run in the section 6.1 order and
every rule in a stage is evaluated (all hits are collected, nothing stops at the first one). A rule whose
input is missing is skipped and traced as "skip(missing)", never evaluated on a guessed value.

Hit messages are built from the YAML message plus numbers, dates and YAML-listed codes only. They never
echo free text from the invoice or the profiles, because the wallet scans reasons for injection and the
UI renders them.

Stages: hard rules, pre-model knock-outs, PD (app/model.py), PD gates, pre-terms review triggers, then
haircuts, terms and pricing, and the rules that need them (KO.NO_HEADROOM, KO.PRICING, REVIEW.CONCENTRATION,
REVIEW.MANDATE_APR).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from app import model
from app.profiles import MISSING, BuyerProfile, SupplierProfile, normalise_buyer, normalise_supplier
from app.rules import Haircut, Rule, RuleSet, active_rules, check_registry
from app.schemas import Mandate, PolicyRequestExt, Portfolio
from app.terms import CENT, Price, Terms, compute_terms, fmt_rate, price
from shared.money import DAYS_PER_YEAR, FEE_PERIOD_DAYS
from shared.schemas import Decision, ExtractedInvoice

Status = Literal["hit", "pass", "skip"]


@dataclass(frozen=True)
class Ctx:
    """What a predicate may read: invoice, normalised profiles, mandate, portfolio, decision date."""

    invoice: ExtractedInvoice
    supplier: SupplierProfile
    buyer: BuyerProfile
    as_of: date
    rules: RuleSet
    mandate: Mandate | None = None
    portfolio: Portfolio | None = None
    pd: Decimal | None = None  # set once the model has run
    prediction: model.Prediction | None = None  # PD, model version and top drivers
    terms: Terms | None = None  # set by the terms stage (None when the buyer tier has no base advance)
    price: Price | None = None

    @property
    def tenor_days(self) -> int:
        return (self.invoice.due_date - self.as_of).days

    @property
    def invoice_age_days(self) -> int:
        return (self.as_of - self.invoice.issue_date).days

    @property
    def line_items_sum(self) -> Decimal:
        return sum((item.total for item in self.invoice.line_items), Decimal(0))


def build_ctx(req: PolicyRequestExt, today: date | None = None, rules: RuleSet | None = None) -> Ctx:
    """Normalise the request. The request's as_of_date wins, else `today`, else the system date.

    Raises ValueError on malformed profiles (HTTP 422 at the endpoint).
    """
    return Ctx(
        invoice=req.invoice,
        supplier=normalise_supplier(req.supplier_profile),
        buyer=normalise_buyer(req.buyer_profile),
        as_of=req.as_of_date or today or date.today(),
        rules=rules or active_rules(),
        mandate=req.mandate,
        portfolio=req.portfolio,
    )


@dataclass(frozen=True)
class Verdict:
    """What a predicate returns: hit (with numeric detail), pass, or skip (with the reason)."""

    status: Status
    detail: str = ""


PASS = Verdict("pass")
SKIP_MISSING = Verdict("skip", "missing")


def hit(detail: str = "") -> Verdict:
    return Verdict("hit", detail)


@dataclass(frozen=True)
class RuleResult:
    id: str
    status: Status
    outcome: Literal["reject", "review"] | None = None  # set on a hit only
    message: str = ""  # YAML message, plus the numbers behind a hit
    skip_reason: str | None = None

    @property
    def trace(self) -> str:
        """rule_trace entry, e.g. "KO.OVERDUE:pass" or "REVIEW.NEW_SUPPLIER:skip(missing)"."""
        return f"{self.id}:skip({self.skip_reason})" if self.status == "skip" else f"{self.id}:{self.status}"


Predicate = Callable[[Ctx, Any], Verdict]
RULES: dict[str, Predicate] = {}

AFTER_TERMS: set[str] = set()  # rules that read the terms or the price, run in the last stage


def rule(rule_id: str, *, after_terms: bool = False) -> Callable[[Predicate], Predicate]:
    """Register a predicate under its YAML id; after_terms=True runs it once terms and price exist."""

    def register(fn: Predicate) -> Predicate:
        if rule_id in RULES:
            raise ValueError(f"predicate already registered for {rule_id}")
        RULES[rule_id] = fn
        if after_terms:
            AFTER_TERMS.add(rule_id)
        return fn

    return register


def _dec(value: float | Decimal) -> Decimal:
    """Floats from the contract (scores) compared exactly: 0.30 -> Decimal("0.3"), never 0.2999999..."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


# --- Hard rules (team-wide, docs/00-scope.md section 4.2): applied before any model ---


@rule("HARD.FRAUD_SCORE")
def _fraud_score(ctx: Ctx, p: Any) -> Verdict:
    score = _dec(ctx.invoice.fraud_score)
    return (
        hit(f"fraud_score {score} >= {fmt_rate(p.min_fraud_score)}") if score >= p.min_fraud_score else PASS
    )


@rule("HARD.INJECTION")
def _injection(ctx: Ctx, p: Any) -> Verdict:
    count = len(ctx.invoice.injection_flags)
    return hit(f"{count} injection flag(s)") if count else PASS


@rule("HARD.LOW_CONFIDENCE")
def _low_confidence(ctx: Ctx, p: Any) -> Verdict:
    confidence = _dec(ctx.invoice.confidence)
    return (
        hit(f"confidence {confidence} < {fmt_rate(p.min_confidence)}")
        if confidence < p.min_confidence
        else PASS
    )


@rule("HARD.KYC_UNKNOWN")
def _kyc_unknown(ctx: Ctx, p: Any) -> Verdict:
    return hit() if ctx.supplier.kyc_valid is MISSING else PASS


# --- Knock-outs evaluated before the model (KO.NO_HEADROOM and KO.PRICING need terms and pricing) ---


def _flag_match(ctx: Ctx, p: Any) -> Verdict:
    """Exact match of OCR fraud flags against the YAML list; only YAML-listed codes are echoed."""
    matched = sorted(set(ctx.invoice.fraud_flags) & set(p.flags))
    return hit("flags " + ", ".join(matched)) if matched else PASS


rule("KO.DUPLICATE")(_flag_match)
rule("KO.PO_MISMATCH")(_flag_match)


@rule("KO.KYC_INVALID")
def _kyc_invalid(ctx: Ctx, p: Any) -> Verdict:
    valid, expiry = ctx.supplier.kyc_valid, ctx.supplier.kyc_expiry
    if valid is False:
        return hit("seller KYC flagged invalid")
    if expiry is not MISSING and expiry < ctx.as_of:
        return hit(f"kyc_expiry {expiry.isoformat()} before {ctx.as_of.isoformat()}")
    return SKIP_MISSING if valid is MISSING else PASS


@rule("KO.OVERDUE")
def _overdue(ctx: Ctx, p: Any) -> Verdict:
    due = ctx.invoice.due_date
    return hit(f"due_date {due.isoformat()} before {ctx.as_of.isoformat()}") if due < ctx.as_of else PASS


@rule("KO.TENOR_TOO_SHORT")
def _tenor_too_short(ctx: Ctx, p: Any) -> Verdict:
    tenor = ctx.tenor_days
    return hit(f"tenor {tenor} days < {p.min_tenor_days}") if tenor < p.min_tenor_days else PASS


@rule("KO.TENOR_TOO_LONG")
def _tenor_too_long(ctx: Ctx, p: Any) -> Verdict:
    tenor = ctx.tenor_days
    return hit(f"tenor {tenor} days > {p.max_tenor_days}") if tenor > p.max_tenor_days else PASS


@rule("KO.TOO_OLD")
def _too_old(ctx: Ctx, p: Any) -> Verdict:
    age = ctx.invoice_age_days
    return hit(f"invoice age {age} days > {p.max_age_days}") if age > p.max_age_days else PASS


@rule("KO.BUYER_TIER")
def _buyer_tier(ctx: Ctx, p: Any) -> Verdict:
    tier = ctx.buyer.credit_tier
    if tier is MISSING:
        return SKIP_MISSING  # REVIEW.THIN_PROFILE handles a buyer with no tier
    return hit(f"tier {tier}") if tier in p.ineligible else PASS


@rule("KO.CURRENCY")
def _currency(ctx: Ctx, p: Any) -> Verdict:
    return PASS if ctx.invoice.currency in ctx.rules.currency_allowlist else hit()


@rule("KO.DATES_INVALID")
def _dates_invalid(ctx: Ctx, p: Any) -> Verdict:
    return hit() if ctx.invoice.due_date < ctx.invoice.issue_date else PASS


# --- PD gates (section 6.1 step 5) ---


@rule("KO.PD_TOO_HIGH")
def _pd_too_high(ctx: Ctx, p: Any) -> Verdict:
    if ctx.pd is None:
        return SKIP_MISSING
    return hit(f"PD {ctx.pd} > {fmt_rate(p.reject_above)}") if ctx.pd > p.reject_above else PASS


@rule("REVIEW.PD_ABOVE_CAP")
def _pd_above_cap(ctx: Ctx, p: Any) -> Verdict:
    """Review above min(review_above, the mandate's max_predicted_default, else the platform default)."""
    if ctx.pd is None:
        return SKIP_MISSING
    mandate_cap = ctx.mandate.max_predicted_default if ctx.mandate else None
    cap = min(p.review_above, ctx.rules.defaults.max_pd if mandate_cap is None else mandate_cap)
    return hit(f"PD {ctx.pd} > cap {fmt_rate(cap)}") if ctx.pd > cap else PASS


# --- Review triggers evaluated before terms (section 6.1 step 6) ---


@rule("REVIEW.UNCONFIRMED_BUYER")
def _unconfirmed_buyer(ctx: Ctx, p: Any) -> Verdict:
    """Missing confirmation counts as unconfirmed (brief 5.3)."""
    return PASS if ctx.buyer.confirmed is True else hit()


def ko_flags(rules: RuleSet) -> set[str]:
    """Every fraud flag a knock-out already handles."""
    return {flag for ko in rules.knockouts for flag in getattr(ko.param, "flags", [])}


@rule("REVIEW.FRAUD_FLAGS")
def _fraud_flags(ctx: Ctx, p: Any) -> Verdict:
    """Any OCR fraud flag no knock-out handles. Only the count is reported, never the flag text."""
    other = set(ctx.invoice.fraud_flags) - ko_flags(ctx.rules)
    return hit(f"{len(other)} other fraud flag(s)") if other else PASS


@rule("REVIEW.LINE_ITEMS_MISMATCH")
def _line_items_mismatch(ctx: Ctx, p: Any) -> Verdict:
    """Line totals must equal the amount, either as is or plus one of the VAT rates, within tolerance."""
    if not ctx.invoice.line_items:
        return SKIP_MISSING
    total, amount = ctx.line_items_sum, ctx.invoice.amount
    if any(abs(total * (1 + vat) - amount) <= p.tolerance for vat in p.vat_rates):
        return PASS
    return hit(f"line items {total} vs amount {amount}")


@rule("REVIEW.NEW_SUPPLIER")
def _new_supplier(ctx: Ctx, p: Any) -> Verdict:
    count = ctx.supplier.invoices_financed_count
    if count is MISSING:
        return SKIP_MISSING
    return hit(f"{count} financed < {p.min_financed}") if count < p.min_financed else PASS


@rule("REVIEW.LARGE_TICKET")
def _large_ticket(ctx: Ctx, p: Any) -> Verdict:
    """amount >= human_review_above (inclusive). The mandate's value wins, else the YAML default."""
    if not p.enabled:
        return Verdict("skip", "disabled")
    threshold = ctx.mandate.human_review_above if ctx.mandate else None
    if threshold is None:
        threshold = ctx.rules.defaults.human_review_above.get(ctx.invoice.currency)
    if threshold is None:
        return SKIP_MISSING
    amount = ctx.invoice.amount
    return hit(f"amount {amount} >= {threshold}") if amount >= threshold else PASS


@rule("REVIEW.THIN_PROFILE")
def _thin_profile(ctx: Ctx, p: Any) -> Verdict:
    return hit(f"terms use tier {p.terms_tier}") if ctx.buyer.credit_tier is MISSING else PASS


# --- Haircuts (section 6.2 terms): a hit lowers the advance, it never changes the decision by itself ---


@rule("TERMS.HAIRCUT_UNCONFIRMED")
def _haircut_unconfirmed(ctx: Ctx, p: Any) -> Verdict:
    return PASS if ctx.buyer.confirmed is True else hit()


@rule("TERMS.HAIRCUT_TENOR")
def _haircut_tenor(ctx: Ctx, p: Any) -> Verdict:
    return hit(f"tenor {ctx.tenor_days} days > {p.tenor_above}") if ctx.tenor_days > p.tenor_above else PASS


@rule("TERMS.HAIRCUT_AGE")
def _haircut_age(ctx: Ctx, p: Any) -> Verdict:
    age = ctx.invoice_age_days
    return hit(f"invoice age {age} days > {p.age_above}") if age > p.age_above else PASS


@rule("TERMS.HAIRCUT_DILUTION")
def _haircut_dilution(ctx: Ctx, p: Any) -> Verdict:
    dilution = ctx.supplier.dilution_rate
    if dilution is MISSING:
        return SKIP_MISSING
    return hit(f"dilution {dilution} > {p.dilution_above}") if dilution > p.dilution_above else PASS


@rule("TERMS.HAIRCUT_PD")
def _haircut_pd(ctx: Ctx, p: Any) -> Verdict:
    if ctx.pd is None:
        return SKIP_MISSING
    return hit(f"PD {ctx.pd} > {p.pd_above}") if ctx.pd > p.pd_above else PASS


# --- Rules that need the terms and the price (section 6.1 steps 7-8) ---


@rule("KO.NO_HEADROOM", after_terms=True)
def _no_headroom(ctx: Ctx, p: Any) -> Verdict:
    if ctx.terms is None:
        return SKIP_MISSING
    return hit(f"remaining limit {ctx.terms.cap.quantize(CENT)}") if ctx.terms.cap <= 0 else PASS


@rule("KO.PRICING", after_terms=True)
def _pricing(ctx: Ctx, p: Any) -> Verdict:
    """Checked on the unclamped annual price: the clamped fee can never exceed the ceiling."""
    if ctx.price is None:
        return SKIP_MISSING
    annual = ctx.price.annual
    return hit(f"annual risk price {annual:.4f} > {fmt_rate(p.max_apr)}") if annual > p.max_apr else PASS


@rule("REVIEW.MANDATE_APR", after_terms=True)
def _mandate_apr(ctx: Ctx, p: Any) -> Verdict:
    """fee_rate x 365/30, unrounded, against the mandate's max_apr."""
    if ctx.price is None or ctx.mandate is None or ctx.mandate.max_apr is None:
        return SKIP_MISSING
    apr = ctx.price.fee_rate * DAYS_PER_YEAR / FEE_PERIOD_DAYS
    return hit(f"APR {apr:.4f} > mandate {ctx.mandate.max_apr}") if apr > ctx.mandate.max_apr else PASS


@rule("REVIEW.CONCENTRATION", after_terms=True)
def _concentration(ctx: Ctx, p: Any) -> Verdict:
    """(current exposure + limit) / pool capacity, for the buyer and for the seller."""
    if ctx.terms is None:
        return SKIP_MISSING
    pool = (
        ctx.portfolio.pool_capacity
        if ctx.portfolio
        else ctx.rules.defaults.pool_capacity.get(ctx.invoice.currency)
    )
    if pool is None:
        return SKIP_MISSING
    limit = ctx.terms.limit
    buyer_share = (ctx.buyer.current_exposure + limit) / pool
    supplier_share = (ctx.supplier.current_exposure + limit) / pool
    if buyer_share > p.max_buyer_share:
        return hit(f"buyer share {buyer_share:.4f} > {p.max_buyer_share}")
    if supplier_share > p.max_supplier_share:
        return hit(f"seller share {supplier_share:.4f} > {p.max_supplier_share}")
    return PASS


check_registry(active_rules(), RULES)  # startup fails if the YAML and the predicates disagree


# --- Evaluation ---


def run_rule(ctx: Ctx, r: Rule | Haircut) -> RuleResult:
    verdict = RULES[r.id](ctx, r.param)
    if verdict.status == "hit":
        message = f"{r.message} ({verdict.detail})" if verdict.detail else r.message
        return RuleResult(r.id, "hit", getattr(r, "outcome", None), message)
    if verdict.status == "skip":
        return RuleResult(r.id, "skip", skip_reason=verdict.detail or "missing")
    return RuleResult(r.id, "pass")


def run_stage(ctx: Ctx, section: Iterable[Rule | Haircut], *, after_terms: bool = False) -> list[RuleResult]:
    """Evaluate the section's rules of this stage, in YAML order, collecting all results."""
    return [run_rule(ctx, r) for r in section if (r.id in AFTER_TERMS) == after_terms]


def run_pre_model(ctx: Ctx) -> list[RuleResult]:
    """Section 6.1 steps 2-3: hard rules, then the knock-outs that don't need terms."""
    return run_stage(ctx, ctx.rules.hard_rules) + run_stage(ctx, ctx.rules.knockouts)


def run_pre_terms(ctx: Ctx) -> tuple[Ctx, list[RuleResult]]:
    """Section 6.1 steps 2-6: hard rules, knock-outs, PD, PD gates, review triggers. Returns ctx with PD."""
    results = run_pre_model(ctx)
    prediction = model.predict(ctx)
    ctx = replace(ctx, pd=Decimal(str(prediction.pd)), prediction=prediction)
    results += run_stage(ctx, ctx.rules.pd_gates) + run_stage(ctx, ctx.rules.review_triggers)
    return ctx, results


def terms_tier(ctx: Ctx) -> str:
    """The buyer's tier, or the YAML's thin-profile tier when the buyer has none."""
    tier = ctx.buyer.credit_tier
    return ctx.rules.rule("REVIEW.THIN_PROFILE").param.terms_tier if tier is MISSING else tier


def run_terms(ctx: Ctx) -> tuple[Ctx, list[RuleResult]]:
    """Section 6.1 steps 7-8: haircuts, terms, pricing, then the rules that need them. Needs ctx.pd.

    A tier with no base advance (D, already knocked out) gets no terms; the rules that need them skip.
    """
    haircut_results = run_stage(ctx, ctx.rules.terms.haircuts)
    tier = terms_tier(ctx)
    if tier in ctx.rules.terms.base_advance_by_tier and ctx.pd is not None:
        applied = [ctx.rules.rule(r.id) for r in haircut_results if r.status == "hit"]
        terms = compute_terms(
            ctx.rules,
            tier=tier,
            amount=ctx.invoice.amount,
            currency=ctx.invoice.currency,
            haircuts=applied,
            buyer=ctx.buyer,
            supplier=ctx.supplier,
            mandate=ctx.mandate,
        )
        quote = price(
            ctx.rules,
            pd=ctx.pd,
            tenor_days=ctx.tenor_days,
            confirmed=ctx.buyer.confirmed is True,
            limit=terms.limit,
        )
        ctx = replace(ctx, terms=terms, price=quote)
    post = run_stage(ctx, ctx.rules.knockouts, after_terms=True)
    post += run_stage(ctx, ctx.rules.review_triggers, after_terms=True)
    return ctx, haircut_results + post


def evaluate(ctx: Ctx) -> tuple[Ctx, list[RuleResult]]:
    """The whole rule pipeline (section 6.1 steps 2-8). Returns ctx with PD, terms and price."""
    ctx, results = run_pre_terms(ctx)
    ctx, more = run_terms(ctx)
    return ctx, results + more


def merge_outcome(results: Iterable[RuleResult]) -> Decision:
    """The most severe hit wins: reject > review > approve."""
    outcomes = {r.outcome for r in results if r.status == "hit"}
    if "reject" in outcomes:
        return Decision.reject
    if "review" in outcomes:
        return Decision.review
    return Decision.approve


def hits(results: Iterable[RuleResult]) -> list[RuleResult]:
    return [r for r in results if r.status == "hit"]


def rule_trace(results: Iterable[RuleResult]) -> list[str]:
    return [r.trace for r in results]
