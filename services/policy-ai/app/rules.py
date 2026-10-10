"""Load and validate the credit rule set in rules/policy.v1.yaml (policy-ai CLAUDE.md sections 6.2, 6.3).

Every section is a pydantic model with extra="forbid", so a typo in the YAML fails at startup instead of
silently switching a rule off. Each rule's `param` block is validated against the parameter model for its
id, so thresholds reach the engine as typed Decimals and ints, never as floats. Nothing in the YAML is
evaluated as code: rule ids are matched by name to Python predicates, and check_registry() fails if the
two sides disagree.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    StringConstraints,
    ValidationError,
    create_model,
    model_validator,
)

DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "policy.v1.yaml"
RULES_PATH_ENV = "POLICY_RULES_PATH"  # override, e.g. a temp copy in tests

Rate = Annotated[Decimal, Field(ge=0, le=1)]
Money = Annotated[Decimal, Field(gt=0, decimal_places=2)]
Count = Annotated[int, Field(ge=0)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
ReasonId = Annotated[str, StringConstraints(pattern=r"^[A-Z]+\.[A-Z][A-Z0-9_]*$")]
Tier = Literal["A", "B", "C", "D"]
ByCurrency = dict[Currency, Money]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Parameters: one strict model per rule id that takes any. Ids not listed here take none. ---


class NoParam(_Strict):
    pass


def _params(rule_id: str, **fields: Any) -> type[_Strict]:
    """A strict parameter model; each field is a type (required) or a (type, default) pair."""
    spec = {name: f if isinstance(f, tuple) else (f, ...) for name, f in fields.items()}
    return create_model(f"{rule_id}.param", __base__=_Strict, **spec)


PARAM_MODELS: dict[str, type[_Strict]] = {
    rule_id: _params(rule_id, **fields)
    for rule_id, fields in {
        "HARD.FRAUD_SCORE": {"min_fraud_score": Rate},
        "HARD.LOW_CONFIDENCE": {"min_confidence": Rate},
        "KO.DUPLICATE": {"flags": Annotated[list[str], Field(min_length=1)]},
        "KO.PO_MISMATCH": {"flags": Annotated[list[str], Field(min_length=1)]},
        "KO.TENOR_TOO_SHORT": {"min_tenor_days": Count},
        "KO.TENOR_TOO_LONG": {"max_tenor_days": Count},
        "KO.TOO_OLD": {"max_age_days": Count},
        "KO.BUYER_TIER": {"ineligible": list[Tier]},
        "KO.PRICING": {"max_apr": Rate},
        "KO.PD_TOO_HIGH": {"reject_above": Rate},
        "REVIEW.PD_ABOVE_CAP": {"review_above": Rate},
        "REVIEW.LINE_ITEMS_MISMATCH": {
            "tolerance": Annotated[Decimal, Field(ge=0)],
            "vat_rates": Annotated[list[Rate], Field(min_length=1)],
        },
        "REVIEW.NEW_SUPPLIER": {"min_financed": Count},
        "REVIEW.LARGE_TICKET": {"enabled": bool, "basis": (Literal["amount"], "amount")},
        "REVIEW.CONCENTRATION": {"max_buyer_share": Rate, "max_supplier_share": Rate},
        "TERMS.HAIRCUT_TENOR": {"tenor_above": Count},
        "TERMS.HAIRCUT_AGE": {"age_above": Count},
        "TERMS.HAIRCUT_DILUTION": {"dilution_above": Rate},
        "TERMS.HAIRCUT_PD": {"pd_above": Rate},
    }.items()
}

# KO.* always rejects and REVIEW.* always reviews; HARD.* must state its outcome.
_IMPLIED_OUTCOME = {"KO": "reject", "REVIEW": "review"}


class _WithParam(_Strict):
    id: ReasonId
    message: str = Field(min_length=1)
    param: SerializeAsAny[_Strict] = NoParam()

    @model_validator(mode="before")
    @classmethod
    def _typed_param(cls, data: Any) -> Any:
        if isinstance(data, dict):
            rule_id = str(data.get("id"))
            try:
                param = PARAM_MODELS.get(rule_id, NoParam).model_validate(data.get("param") or {})
            except ValidationError as exc:
                problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
                raise ValueError(f"{rule_id} param: {problems}") from None
            data = {**data, "param": param}
        return data


class Rule(_WithParam):
    """A hard rule, knock-out, PD gate or review trigger."""

    outcome: Literal["reject", "review"]

    @model_validator(mode="before")
    @classmethod
    def _implied_outcome(cls, data: Any) -> Any:
        if isinstance(data, dict):
            implied = _IMPLIED_OUTCOME.get(str(data.get("id", "")).split(".")[0])
            if implied is not None:
                if data.get("outcome", implied) != implied:
                    raise ValueError(f"{data.get('id')}: outcome must be {implied}")
                data = {**data, "outcome": implied}
        return data


class Haircut(_WithParam):
    minus: Annotated[Decimal, Field(gt=0, le=1)]


class ReasonCode(_Strict):
    id: ReasonId
    message: str = Field(min_length=1)


class Defaults(_Strict):
    pool_capacity: ByCurrency
    max_pd: Rate
    human_review_above: ByCurrency


class Terms(_Strict):
    base_advance_by_tier: dict[Tier, Rate]
    haircuts: list[Haircut]
    floor_advance: Rate
    max_single_invoice_limit: ByCurrency
    caps: list[ReasonCode]

    @model_validator(mode="after")
    def _eligible_tiers_priced(self) -> Terms:
        missing = {"A", "B", "C"} - set(self.base_advance_by_tier)
        if missing:
            raise ValueError(f"base_advance_by_tier is missing tiers {sorted(missing)}")
        return self


class Pricing(_Strict):
    id: ReasonId
    message: str = Field(min_length=1)
    cost_of_funds: Rate
    margin: Rate
    unconfirmed_premium: Rate
    min_pricing_tenor_days: Annotated[int, Field(gt=0)]
    fee_step: Annotated[Decimal, Field(gt=0, le=1)]
    min_fee_rate: Rate
    max_fee_rate: Rate

    @model_validator(mode="after")
    def _fee_range(self) -> Pricing:
        if self.min_fee_rate > self.max_fee_rate:
            raise ValueError("min_fee_rate is above max_fee_rate")
        return self


class MandateDefaults(_Strict):
    max_ltv: Rate
    max_apr: Rate
    max_predicted_default: Rate
    max_amount_per_tx: ByCurrency
    daily_cap: ByCurrency


class MandateLimits(_Strict):
    """Platform maxima for the mandate compiler: a mandate may tighten these, never loosen them."""

    max_ltv: Rate
    max_apr: Rate
    max_predicted_default: Rate
    max_amount_per_tx: ByCurrency
    daily_cap: ByCurrency
    human_review_above: ByCurrency
    defaults: MandateDefaults
    default_validity_days: Annotated[int, Field(gt=0)]
    max_validity_days: Annotated[int, Field(gt=0)]
    registered_payees: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _defaults_within_maxima(self) -> MandateLimits:
        d = self.defaults
        for name in ("max_ltv", "max_apr", "max_predicted_default"):
            if getattr(d, name) > getattr(self, name):
                raise ValueError(f"default {name} is above the platform maximum")
        for name in ("max_amount_per_tx", "daily_cap"):
            ceiling = getattr(self, name)
            for ccy, value in getattr(d, name).items():
                if ccy not in ceiling or value > ceiling[ccy]:
                    raise ValueError(f"default {name} {ccy} is above the platform ceiling")
        if self.default_validity_days > self.max_validity_days:
            raise ValueError("default_validity_days is above max_validity_days")
        return self


_SECTION_PREFIXES = {
    "hard_rules": ("HARD",),
    "knockouts": ("KO",),
    "pd_gates": ("KO", "REVIEW"),
    "review_triggers": ("REVIEW",),
}


class RuleSet(_Strict):
    version: Annotated[str, StringConstraints(pattern=r"^credit-policy-v\d+\.\d+$")]
    currency_allowlist: list[Currency] = Field(min_length=1)
    lgd: Rate
    decision_ttl_hours: Annotated[int, Field(gt=0)]
    defaults: Defaults
    hard_rules: list[Rule]
    knockouts: list[Rule]
    pd_gates: list[Rule]
    review_triggers: list[Rule]
    terms: Terms
    pricing: Pricing
    mandate_limits: MandateLimits

    @model_validator(mode="after")
    def _consistent(self) -> RuleSet:
        for section, prefixes in _SECTION_PREFIXES.items():
            for rule in getattr(self, section):
                if rule.id.split(".")[0] not in prefixes:
                    raise ValueError(f"{section}: {rule.id} does not belong in this section")
        for haircut in self.terms.haircuts:
            if not haircut.id.startswith("TERMS.HAIRCUT_"):
                raise ValueError(f"terms.haircuts: {haircut.id} must start with TERMS.HAIRCUT_")
        ids = self.rule_ids() + [c.id for c in self.terms.caps] + [self.pricing.id]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate rule ids: {dupes}")
        per_currency = {
            "defaults.pool_capacity": self.defaults.pool_capacity,
            "defaults.human_review_above": self.defaults.human_review_above,
            "terms.max_single_invoice_limit": self.terms.max_single_invoice_limit,
            "mandate_limits.max_amount_per_tx": self.mandate_limits.max_amount_per_tx,
            "mandate_limits.daily_cap": self.mandate_limits.daily_cap,
            "mandate_limits.human_review_above": self.mandate_limits.human_review_above,
        }
        for name, table in per_currency.items():
            missing = set(self.currency_allowlist) - set(table)
            if missing:
                raise ValueError(f"{name} has no value for {sorted(missing)}")
        return self

    def predicate_rules(self) -> list[Rule | Haircut]:
        """Every entry that needs a Python predicate, in evaluation order (brief 6.1)."""
        return [
            *self.hard_rules,
            *self.knockouts,
            *self.pd_gates,
            *self.review_triggers,
            *self.terms.haircuts,
        ]

    def rule_ids(self) -> list[str]:
        return [r.id for r in self.predicate_rules()]

    def rule(self, rule_id: str) -> Rule | Haircut:
        for r in self.predicate_rules():
            if r.id == rule_id:
                return r
        raise KeyError(rule_id)


class RegistryError(ValueError):
    """The YAML and the Python predicate registry disagree (brief 6.3): startup must fail."""


def check_registry(rules: RuleSet, registry: Iterable[str]) -> None:
    """Fail if the YAML names an id with no predicate, or a predicate has no YAML entry."""
    yaml_ids, code_ids = set(rules.rule_ids()), set(registry)
    problems = []
    if yaml_ids - code_ids:
        problems.append(f"no predicate for {sorted(yaml_ids - code_ids)}")
    if code_ids - yaml_ids:
        problems.append(f"no YAML entry for {sorted(code_ids - yaml_ids)}")
    if problems:
        raise RegistryError("; ".join(problems))


def rules_path() -> Path:
    return Path(os.environ.get(RULES_PATH_ENV) or DEFAULT_RULES_PATH)


def load_rules(path: str | Path | None = None) -> RuleSet:
    """Parse and validate a rule set. safe_load only: the YAML can never construct Python objects."""
    source = Path(path) if path is not None else rules_path()
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: expected a mapping at the top level")
    return RuleSet.model_validate(raw)


@lru_cache(maxsize=1)
def active_rules() -> RuleSet:
    """The rule set the service runs with, loaded once. Clear the cache after changing POLICY_RULES_PATH."""
    return load_rules()


active_rules()  # validate at import, so a broken rule set stops the service from starting
