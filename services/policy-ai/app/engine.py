"""Credit rule engine (services/policy-ai/CLAUDE.md sections 6.1 and 6.3).

Each rule is a small Python predicate registered under its YAML id; the YAML holds only the parameters,
so no threshold lives here and nothing is ever evaluated as code. Stages run in the section 6.1 order and
every rule in a stage is evaluated (all hits are collected, nothing stops at the first one). A rule whose
input is missing is skipped and traced as "skip(missing)", never evaluated on a guessed value.

Hit messages are built from the YAML message plus numbers, dates and YAML-listed codes only. They never
echo free text from the invoice or the profiles, because the wallet scans reasons for injection and the
UI renders them.

This part covers the context, the registry, the hard rules and the pre-model knock-outs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from app.profiles import MISSING, BuyerProfile, SupplierProfile, normalise_buyer, normalise_supplier
from app.rules import Rule, RuleSet, active_rules, check_registry
from app.schemas import Mandate, PolicyRequestExt, Portfolio
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

# YAML ids whose predicates arrive with the later stages (PD gates, review triggers, terms and pricing).
# The import-time registry check accepts them until then; each later stage removes its ids from this set.
PENDING: frozenset[str] = frozenset(
    {
        "KO.NO_HEADROOM",
        "KO.PRICING",
        "KO.PD_TOO_HIGH",
        "REVIEW.PD_ABOVE_CAP",
        "REVIEW.UNCONFIRMED_BUYER",
        "REVIEW.FRAUD_FLAGS",
        "REVIEW.LINE_ITEMS_MISMATCH",
        "REVIEW.NEW_SUPPLIER",
        "REVIEW.LARGE_TICKET",
        "REVIEW.CONCENTRATION",
        "REVIEW.THIN_PROFILE",
        "REVIEW.MANDATE_APR",
        "TERMS.HAIRCUT_UNCONFIRMED",
        "TERMS.HAIRCUT_TENOR",
        "TERMS.HAIRCUT_AGE",
        "TERMS.HAIRCUT_DILUTION",
        "TERMS.HAIRCUT_PD",
    }
)


def rule(rule_id: str) -> Callable[[Predicate], Predicate]:
    """Register a predicate under its YAML id."""

    def register(fn: Predicate) -> Predicate:
        if rule_id in RULES:
            raise ValueError(f"predicate already registered for {rule_id}")
        RULES[rule_id] = fn
        return fn

    return register


def _dec(value: float | Decimal) -> Decimal:
    """Floats from the contract (scores) compared exactly: 0.30 -> Decimal("0.3"), never 0.2999999..."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


# --- Hard rules (team-wide, docs/00-scope.md section 4.2): applied before any model ---


@rule("HARD.FRAUD_SCORE")
def _fraud_score(ctx: Ctx, p: Any) -> Verdict:
    score = _dec(ctx.invoice.fraud_score)
    return hit(f"fraud_score {score} >= {p.min_fraud_score}") if score >= p.min_fraud_score else PASS


@rule("HARD.INJECTION")
def _injection(ctx: Ctx, p: Any) -> Verdict:
    count = len(ctx.invoice.injection_flags)
    return hit(f"{count} injection flag(s)") if count else PASS


@rule("HARD.LOW_CONFIDENCE")
def _low_confidence(ctx: Ctx, p: Any) -> Verdict:
    confidence = _dec(ctx.invoice.confidence)
    return hit(f"confidence {confidence} < {p.min_confidence}") if confidence < p.min_confidence else PASS


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


check_registry(active_rules(), [*RULES, *PENDING])  # startup fails if the YAML and the predicates disagree


# --- Evaluation ---


def run_rule(ctx: Ctx, r: Rule) -> RuleResult:
    verdict = RULES[r.id](ctx, r.param)
    if verdict.status == "hit":
        message = f"{r.message} ({verdict.detail})" if verdict.detail else r.message
        return RuleResult(r.id, "hit", r.outcome, message)
    if verdict.status == "skip":
        return RuleResult(r.id, "skip", skip_reason=verdict.detail or "missing")
    return RuleResult(r.id, "pass")


def run_stage(ctx: Ctx, section: Iterable[Rule]) -> list[RuleResult]:
    """Evaluate every registered rule of a section, in YAML order, collecting all results."""
    return [run_rule(ctx, r) for r in section if r.id in RULES]


def run_pre_model(ctx: Ctx) -> list[RuleResult]:
    """Section 6.1 steps 2-3: hard rules, then knock-outs.

    KO.NO_HEADROOM and KO.PRICING are still in PENDING; when the terms stage registers them it must also run
    them after terms instead of here.
    """
    return run_stage(ctx, ctx.rules.hard_rules) + run_stage(ctx, ctx.rules.knockouts)


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
