"""Policy-ai request and response models (services/policy-ai/CLAUDE.md section 5.2).

These subclass the shared contract in shared/schemas.py and only ADD optional request fields and extra
response fields. Shared fields (apr, pd, decision_id, decision_hash, ...) are never redeclared here; the
engine always fills them. A PolicyDecisionExt dumped to JSON therefore still validates as the shared
PolicyDecision, which is the view the agent wallet parses and hashes.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from shared.schemas import PolicyDecision, PolicyRequest, Reason


class Portfolio(BaseModel):
    """Pool-level exposure, used for the concentration check. Defaults come from the YAML rule set."""

    total_exposure: Decimal = Field(default=Decimal("0.00"), ge=0)
    pool_capacity: Decimal = Field(gt=0)


class Mandate(BaseModel):
    """The SME's active mandate as /policy/decide reads it (input side only).

    Key names are the agent wallet's (its CLAUDE.md section 5.2); the older names are accepted as aliases.
    Every field is optional: a field that is not passed simply does not constrain the decision.
    Unknown keys (the wallet's own additions such as version, payee_allowlist, mandate_hash) are ignored,
    so the wallet's stored mandate can be forwarded as is.
    """

    model_config = ConfigDict(extra="ignore")

    mandate_id: str | None = None
    max_ltv: Decimal | None = Field(
        default=None, gt=0, le=1, validation_alias=AliasChoices("max_ltv", "max_advance_rate")
    )
    max_apr: Decimal | None = Field(default=None, gt=0, le=1)
    max_predicted_default: Decimal | None = Field(
        default=None, gt=0, le=1, validation_alias=AliasChoices("max_predicted_default", "max_pd")
    )
    # inclusive: amount >= human_review_above needs a human
    human_review_above: Decimal | None = Field(
        default=None, gt=0, validation_alias=AliasChoices("human_review_above", "human_review_above_thb")
    )
    max_amount_per_tx: Decimal | None = Field(default=None, gt=0)
    daily_cap: Decimal | None = Field(default=None, gt=0)  # enforced by the wallet only
    allowed_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        validation_alias=AliasChoices("allowed_currency", "currency"),
    )
    expires_at: datetime | None = None


class PolicyRequestExt(PolicyRequest):
    """Body of POST /policy/decide: the shared PolicyRequest plus optional extras."""

    portfolio: Portfolio | None = None
    mandate: Mandate | None = None
    as_of_date: date | None = None  # decision date; defaults to today. Fixes tenor and age for tests


class ReasonDetail(Reason):
    """Structured form of one entry in `reasons` (which stays a list of "CODE: message" strings)."""

    source: Literal["rule", "model"]
    effect: str  # what it did, e.g. "reject", "review", "advance_rate 0.80 -> 0.70"


class FeatureContribution(BaseModel):
    """One model driver: feature name, its value for this request and its contribution to the score."""

    feature: str
    value: float | None = None
    contribution: float


class PolicyDecisionExt(PolicyDecision):
    """Response of POST /policy/decide: the shared PolicyDecision plus explanation and audit fields."""

    expected_loss: Decimal = Field(ge=0)  # PD x LGD x limit
    tenor_days: int  # due_date - as_of_date
    fee_amount: Decimal = Field(ge=0)  # limit x fee_rate x tenor_days / 30
    reason_details: list[ReasonDetail] = []
    top_features: list[FeatureContribution] = []
    rule_trace: list[str] = []  # "HARD.FRAUD_SCORE:pass", "REVIEW.NEW_SUPPLIER:skip(missing)"
    valid_until: datetime  # the wallet must not execute after this
    as_of_date: date
    request_hash: str  # "0x" + hash of the effective request (incl. as_of_date and mandate)
