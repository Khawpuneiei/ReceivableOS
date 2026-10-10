"""Model features, built by one function for both training and serving (services/policy-ai/CLAUDE.md 8.2).

Every feature is known at decision time (no leakage). Missing profile values are imputed with the median
of the buyer's tier, taken from the training split and stored with the model; a buyer with no tier is
scored with the medians of the model's `missing_tier`. With `medians=None` (training, first pass) a
missing value comes back as NaN so the trainer can compute those medians.
Pure Python on purpose: serving must not need numpy.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.profiles import MISSING, TIERS, BuyerProfile, SupplierProfile

SECTORS = ("retail", "manufacturing", "food", "construction", "logistics")  # anything else = "other" (all 0)

FEATURES = (
    "buyer_tier_ord",
    "buyer_late_payment_rate",
    "buyer_avg_days_late",
    "buyer_confirmed",
    "log1p_relationship_months",
    "log1p_supplier_years_in_business",
    "log1p_supplier_invoices_financed_count",
    "supplier_historical_default_rate",
    "supplier_dilution_rate",
    "supplier_on_time_ratio",
    "log_amount",
    "tenor_days",
    "invoice_age_days",
    "amount_to_buyer_limit",
    "ocr_confidence",
    "fraud_score",
    *(f"sector_{s}" for s in SECTORS),
)

# Features a profile may leave out; these are imputed with tier medians.
IMPUTABLE = (
    "buyer_late_payment_rate",
    "buyer_avg_days_late",
    "log1p_supplier_years_in_business",
    "log1p_supplier_invoices_financed_count",
    "supplier_historical_default_rate",
    "supplier_dilution_rate",
    "supplier_on_time_ratio",
    "amount_to_buyer_limit",
)

# Expected direction of each feature on PD: +1 raises it, -1 lowers it, 0 either way (LightGBM constraints).
MONOTONE = {
    "buyer_tier_ord": 1,
    "buyer_late_payment_rate": 1,
    "buyer_avg_days_late": 1,
    "buyer_confirmed": -1,
    "log1p_relationship_months": -1,
    "log1p_supplier_years_in_business": -1,
    "log1p_supplier_invoices_financed_count": -1,
    "supplier_historical_default_rate": 1,
    "supplier_dilution_rate": 1,
    "supplier_on_time_ratio": -1,
    "log_amount": 1,
    "tenor_days": 1,
    "invoice_age_days": 1,
    "amount_to_buyer_limit": 1,
    "ocr_confidence": -1,
    "fraud_score": 1,
    **{f"sector_{s}": 0 for s in SECTORS},
}


@dataclass(frozen=True)
class FeatureVector:
    values: dict[str, float]  # in FEATURES order
    imputed: frozenset[str]  # features that took a tier median (or NaN when no medians were given)

    def row(self) -> list[float]:
        return [self.values[name] for name in FEATURES]


def _get(invoice: Any, key: str) -> Any:
    return invoice[key] if isinstance(invoice, Mapping) else getattr(invoice, key)


def _date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _num(value: Any) -> float | None:
    return None if value is MISSING else float(value)


def build_features(
    invoice: Any,
    supplier: SupplierProfile,
    buyer: BuyerProfile,
    as_of: date,
    medians: Mapping[str, Any] | None = None,
) -> FeatureVector:
    """Feature vector for one invoice. `invoice` is an ExtractedInvoice or a mapping with amount,
    issue_date, due_date, confidence and fraud_score. `medians` is {"missing_tier": T, "tiers": {T: {...}}}.
    """
    tier = buyer.credit_tier
    if tier is MISSING:
        tier = medians["missing_tier"] if medians else None
    amount = float(_get(invoice, "amount"))
    limit = _num(buyer.buyer_limit)
    years, financed = _num(supplier.years_in_business), _num(supplier.invoices_financed_count)
    raw: dict[str, float | None] = {
        "buyer_tier_ord": float(TIERS.index(tier)) if tier is not None else None,
        "buyer_late_payment_rate": _num(buyer.late_payment_rate),
        "buyer_avg_days_late": _num(buyer.avg_days_late),
        "buyer_confirmed": 1.0 if buyer.confirmed is True else 0.0,  # missing counts as not confirmed
        "log1p_relationship_months": math.log1p(buyer.relationship_months),
        "log1p_supplier_years_in_business": math.log1p(years) if years is not None else None,
        "log1p_supplier_invoices_financed_count": math.log1p(financed) if financed is not None else None,
        "supplier_historical_default_rate": _num(supplier.historical_default_rate),
        "supplier_dilution_rate": _num(supplier.dilution_rate),
        "supplier_on_time_ratio": _num(supplier.on_time_ratio),
        "log_amount": math.log(amount),
        "tenor_days": float((_date(_get(invoice, "due_date")) - as_of).days),
        "invoice_age_days": float((as_of - _date(_get(invoice, "issue_date"))).days),
        "amount_to_buyer_limit": amount / limit if limit else None,
        "ocr_confidence": float(_get(invoice, "confidence")),
        "fraud_score": float(_get(invoice, "fraud_score")),
        **{f"sector_{s}": 1.0 if buyer.sector == s else 0.0 for s in SECTORS},
    }
    imputed = frozenset(name for name, value in raw.items() if value is None)
    if buyer.credit_tier is MISSING:
        imputed |= {"buyer_tier_ord"}  # scored with the missing tier
    tier_medians = medians["tiers"][tier] if medians and tier is not None else {}
    values = {
        name: (raw[name] if raw[name] is not None else float(tier_medians.get(name, math.nan)))
        for name in FEATURES
    }
    return FeatureVector(values=values, imputed=imputed)
