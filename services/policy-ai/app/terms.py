"""Advance, limit and risk-based fee (services/policy-ai/CLAUDE.md section 6.2, terms algorithm and pricing).

Pure Decimal arithmetic; every number comes from the YAML rule set, the mandate or the profiles. Rounding
keeps the limit at or under every cap and `advance_rate x amount` within 0.01 of the limit: the rate is
floored to 4 decimal places first, then the limit is floored to the cent. Each step that changes a number
is recorded with its reason id and the before/after values.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, Decimal

from app.profiles import MISSING, BuyerProfile, SupplierProfile
from app.rules import Haircut, RuleSet
from app.schemas import Mandate
from shared.money import DAYS_PER_YEAR, FEE_PERIOD_DAYS, TOKEN_DECIMALS, fee_rate_30d_to_apr

RATE_QUANTUM = Decimal("0.0001")  # advance_rate is reported with 4 decimal places
RATE_DISPLAY = Decimal("0.01")  # rates are shown with at least 2 decimal places ("0.70")
CENT = Decimal(1).scaleb(-TOKEN_DECIMALS)  # money has the settlement token's 2 decimals


@dataclass(frozen=True)
class Step:
    """One change to a number, reported as a reason: code, YAML message, e.g. "advance_rate 0.80 -> 0.70"."""

    code: str
    message: str
    effect: str


@dataclass(frozen=True)
class Terms:
    tier: str
    advance: Decimal  # after haircuts, floor and mandate cap
    cap: Decimal  # min(advance x amount, every money cap); <= 0 means no headroom
    advance_rate: Decimal  # floor(cap / amount, 4 dp)
    limit: Decimal  # floor(advance_rate x amount, 0.01)
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Price:
    annual: Decimal  # unclamped annual risk price, checked by KO.PRICING
    fee_rate: Decimal  # per 30 days, rounded up to the fee step and clamped
    apr: Decimal  # reported, via shared.money
    fee_amount: Decimal  # limit x fee_rate x tenor / 30
    expected_loss: Decimal  # PD x LGD x limit
    steps: tuple[Step, ...]


def fmt_rate(value: Decimal) -> Decimal:
    """Drop trailing zeros but keep 2 decimal places: 0.7000 -> 0.70, 0.0090 -> 0.009, 0.1095 -> 0.1095."""
    v = value.normalize()
    return v.quantize(RATE_DISPLAY) if v.as_tuple().exponent > RATE_DISPLAY.as_tuple().exponent else v


def _message(rules: RuleSet, code: str) -> str:
    return next(c.message for c in rules.terms.caps if c.id == code)


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_DOWN)


def compute_terms(
    rules: RuleSet,
    *,
    tier: str,
    amount: Decimal,
    currency: str,
    haircuts: list[Haircut],
    buyer: BuyerProfile,
    supplier: SupplierProfile,
    mandate: Mandate | None,
) -> Terms:
    """Base advance by tier -> haircuts -> floor -> mandate cap -> money caps -> rounded rate and limit."""
    t = rules.terms
    steps: list[Step] = []
    advance = t.base_advance_by_tier[tier]
    for h in haircuts:
        steps.append(
            Step(h.id, h.message, f"advance_rate {fmt_rate(advance)} -> {fmt_rate(advance - h.minus)}")
        )
        advance -= h.minus
    if advance < t.floor_advance:
        code = "TERMS.FLOOR"
        effect = f"advance_rate {fmt_rate(advance)} -> {fmt_rate(t.floor_advance)}"
        steps.append(Step(code, _message(rules, code), effect))
        advance = t.floor_advance
    if mandate is not None and mandate.max_ltv is not None and mandate.max_ltv < advance:
        code = "TERMS.MANDATE_CAP"
        effect = f"advance_rate {fmt_rate(advance)} -> {fmt_rate(mandate.max_ltv)}"
        steps.append(Step(code, _message(rules, code), effect))
        advance = mandate.max_ltv

    caps: list[tuple[str, Decimal]] = []
    for code, limit, exposure, label in (
        ("TERMS.CAP_BUYER_LIMIT", buyer.buyer_limit, buyer.current_exposure, "buyer"),
        ("TERMS.CAP_FACILITY", supplier.facility_limit, supplier.current_exposure, "facility"),
    ):
        if limit is MISSING:
            continue
        headroom = limit - exposure
        if exposure > 0:
            code_h = "TERMS.HEADROOM"
            steps.append(Step(code_h, _message(rules, code_h), f"{label} headroom {_money(headroom)}"))
        caps.append((code, headroom))
    if currency in t.max_single_invoice_limit:
        caps.append(("TERMS.CAP_SINGLE_INVOICE", t.max_single_invoice_limit[currency]))
    if mandate is not None and mandate.max_amount_per_tx is not None:
        caps.append(("TERMS.CAP_MANDATE_TX", mandate.max_amount_per_tx))

    cap = advance * amount
    for code, value in caps:
        if value < cap:
            steps.append(Step(code, _message(rules, code), f"limit {_money(cap)} -> {_money(value)}"))
            cap = value
    if cap <= 0:
        return Terms(tier, advance, cap, Decimal(0), Decimal(0).quantize(CENT), tuple(steps))
    advance_rate = (cap / amount).quantize(RATE_QUANTUM, rounding=ROUND_DOWN)
    return Terms(tier, advance, cap, advance_rate, _money(advance_rate * amount), tuple(steps))


def price(rules: RuleSet, *, pd: Decimal, tenor_days: int, confirmed: bool, limit: Decimal) -> Price:
    """Risk-based fee per 30 days.

    annual = cost of funds + margin + PD x LGD x 365 / max(tenor, min pricing tenor) [+ unconfirmed premium]
    fee_rate = annual x 30/365 rounded up to the fee step, clamped to [min_fee_rate, max_fee_rate]
    """
    p = rules.pricing
    annual = (
        p.cost_of_funds
        + p.margin
        + pd * rules.lgd * DAYS_PER_YEAR / max(tenor_days, p.min_pricing_tenor_days)
    )
    if not confirmed:
        annual += p.unconfirmed_premium
    stepped = (annual * FEE_PERIOD_DAYS / DAYS_PER_YEAR / p.fee_step).to_integral_value(
        ROUND_CEILING
    ) * p.fee_step
    fee_rate = min(max(stepped, p.min_fee_rate), p.max_fee_rate)
    apr = fee_rate_30d_to_apr(fee_rate)
    fee_amount = (limit * fee_rate * max(tenor_days, 0) / FEE_PERIOD_DAYS).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    expected_loss = (pd * rules.lgd * limit).quantize(CENT, rounding=ROUND_HALF_UP)
    effect = (
        f"fee_rate {fmt_rate(fee_rate)} per 30 days (APR {fmt_rate(apr)}; annual risk price {annual:.4f})"
    )
    return Price(annual, fee_rate, apr, fee_amount, expected_loss, (Step(p.id, p.message, effect),))
