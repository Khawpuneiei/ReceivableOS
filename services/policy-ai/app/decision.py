"""POST /policy/decide: run the rule pipeline and package the decision (policy-ai CLAUDE.md 5.2, 6.1).

Response rules: reject => advance_rate 0, limit 0.00, fee_rate 0 and at least one HARD/KO reason; review =>
the terms that would apply and at least one HARD/REVIEW reason; approve => no KO/REVIEW hit. Reasons are
"CODE: message" strings built from YAML text and numbers only, never from invoice or profile text.

When the request carries no mandate, the policy's default mandate (rules/default_mandate.json, or the file
named by POLICY_DEFAULT_MANDATE_FILE) is applied and reported as MANDATE.DEFAULT. A mandate can only tighten
the terms, and the default is checked against the platform maxima when it loads. A request mandate wins.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from app import model
from app.engine import build_ctx, evaluate, merge_outcome
from app.hashing import canonical_json, decision_hash, sha256_hex
from app.rules import RuleSet, active_rules
from app.schemas import FeatureContribution, Mandate, PolicyDecisionExt, PolicyRequestExt, ReasonDetail
from app.terms import CENT, fmt_rate
from shared.schemas import Decision

DEFAULT_MANDATE_PATH = Path(__file__).resolve().parents[1] / "rules" / "default_mandate.json"
DEFAULT_MANDATE_ENV = "POLICY_DEFAULT_MANDATE_FILE"


class InvalidRequest(ValueError):
    """The request can't be decided (HTTP 422): non-positive amount, malformed profile, unknown tier."""


def load_default_mandate(path: str | Path | None = None, rules: RuleSet | None = None) -> Mandate:
    """Load and check the policy's default mandate. It must never be looser than the platform maxima."""
    rules = rules or active_rules()
    source = Path(path or os.environ.get(DEFAULT_MANDATE_ENV) or DEFAULT_MANDATE_PATH)
    raw = json.loads(source.read_text(encoding="utf-8"))
    unknown = set(raw) - set(Mandate.model_fields)
    if unknown:
        raise ValueError(f"{source}: unknown mandate keys {sorted(unknown)}")
    mandate = Mandate.model_validate(raw)
    limits = rules.mandate_limits
    for name in ("max_ltv", "max_apr", "max_predicted_default"):
        value = getattr(mandate, name)
        if value is not None and value > getattr(limits, name):
            raise ValueError(f"{source}: {name} {value} is above the platform maximum")
    ccy = mandate.allowed_currency
    for name in ("max_amount_per_tx", "daily_cap", "human_review_above"):
        value, ceiling = getattr(mandate, name), getattr(limits, name)
        if value is not None and (ccy not in ceiling or value > ceiling[ccy]):
            raise ValueError(
                f"{source}: {name} needs allowed_currency and must not exceed the platform ceiling"
            )
    return mandate


@lru_cache(maxsize=1)
def default_mandate() -> Mandate:
    """The default mandate the service runs with, loaded once. Clear the cache after changing the env var."""
    return load_default_mandate()


def _for_currency(mandate: Mandate, currency: str) -> Mandate:
    """The default mandate's money caps apply only to invoices in its currency; rate caps always apply."""
    if mandate.allowed_currency in (None, currency):
        return mandate
    return mandate.model_copy(
        update={"human_review_above": None, "max_amount_per_tx": None, "daily_cap": None}
    )


def decide(
    req: PolicyRequestExt,
    *,
    now: datetime | None = None,
    rules: RuleSet | None = None,
    use_default_mandate: bool = True,
) -> PolicyDecisionExt:
    rules = rules or active_rules()
    now = now or datetime.now(timezone.utc)
    if req.invoice.amount <= 0:
        raise InvalidRequest("invoice amount must be positive")

    details: list[ReasonDetail] = []
    if req.mandate is not None:
        mandate_trace = "MANDATE.DEFAULT:skip(request-mandate)"
    elif use_default_mandate:
        req = req.model_copy(update={"mandate": _for_currency(default_mandate(), req.invoice.currency)})
        mandate_trace = "MANDATE.DEFAULT:applied"
        message = "No mandate in the request; the policy default mandate applies"
        details.append(ReasonDetail(code="MANDATE.DEFAULT", message=message, source="rule", effect="applied"))
    else:
        mandate_trace = "MANDATE.DEFAULT:skip(disabled)"

    try:
        ctx = build_ctx(req, today=now.astimezone().date(), rules=rules)
    except ValueError as exc:
        raise InvalidRequest(str(exc)) from None
    ctx, results = evaluate(ctx)
    outcome = merge_outcome(results)

    for r in results:
        if r.status == "hit" and r.outcome is not None:
            details.append(ReasonDetail(code=r.id, message=r.message, source="rule", effect=r.outcome))
    prediction = ctx.prediction or model.predict(ctx)
    details += _model_details(prediction)
    zero = Decimal(0)
    if outcome == Decision.reject or ctx.terms is None or ctx.price is None:
        advance_rate, limit, fee_rate, apr = zero, zero.quantize(CENT), zero, zero
        fee_amount = expected_loss = zero.quantize(CENT)
    else:
        for step in ctx.terms.steps + ctx.price.steps:
            details.append(
                ReasonDetail(code=step.code, message=step.message, source="rule", effect=step.effect)
            )
        advance_rate, limit = ctx.terms.advance_rate, ctx.terms.limit
        fee_rate, apr = ctx.price.fee_rate, ctx.price.apr
        fee_amount, expected_loss = ctx.price.fee_amount, ctx.price.expected_loss

    effective_request = {**req.model_dump(mode="json"), "as_of_date": ctx.as_of.isoformat()}
    request_hash = sha256_hex(canonical_json(effective_request))
    versions = {
        "request_hash": request_hash,
        "policy_version": rules.version,
        "model_version": prediction.version,
    }
    pd = float(ctx.pd) if ctx.pd is not None else 0.0
    decision = PolicyDecisionExt(
        decision=outcome,
        advance_rate=fmt_rate(advance_rate),
        limit=limit,
        fee_rate=fmt_rate(fee_rate),
        apr=fmt_rate(apr),
        risk_score=pd,
        pd=pd,
        reasons=[_reason_text(d) for d in details],
        model_version=prediction.version,
        policy_version=rules.version,
        decision_id="dec_" + sha256_hex(canonical_json(versions))[2:26],
        expected_loss=expected_loss,
        top_features=[
            FeatureContribution(feature=d.feature, value=d.value, contribution=d.contribution)
            for d in prediction.drivers
        ],
        tenor_days=ctx.tenor_days,
        fee_amount=fee_amount,
        reason_details=details,
        rule_trace=[mandate_trace, *(r.trace for r in results)],
        valid_until=now + timedelta(hours=rules.decision_ttl_hours),
        as_of_date=ctx.as_of,
        request_hash=request_hash,
    )
    return decision.model_copy(update={"decision_hash": decision_hash(decision)})


def _model_details(prediction: model.Prediction) -> list[ReasonDetail]:
    """MODEL.PD plus one MODEL.* line per top driver (fixed labels and numbers only)."""
    details = [
        ReasonDetail(
            code="MODEL.PD",
            message=f"Predicted buyer default {prediction.pd:.2%} ({prediction.version})",
            source="model",
            effect=f"pd {prediction.pd:.6f}",
        )
    ]
    for driver in prediction.drivers:
        code, message = model.describe(driver)
        effect = f"{driver.contribution:+.4f} log-odds"
        details.append(ReasonDetail(code=code, message=message, source="model", effect=effect))
    return details


def _reason_text(d: ReasonDetail) -> str:
    """ "CODE: message", plus the before/after numbers for a terms step."""
    if d.effect in ("reject", "review", "applied"):
        return f"{d.code}: {d.message}"
    return f"{d.code}: {d.message} ({d.effect})"
