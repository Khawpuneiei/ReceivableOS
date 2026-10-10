"""Probability of default (PD) for the credit decision (policy-ai CLAUDE.md section 8.6, prompt 2).

Placeholder until the trained model lands: a fixed logistic formula over the buyer's tier, late-payment
rate and confirmation and the tenor. It is deterministic, makes no network call and reports
model_version "scorecard-fallback", the same version the trained model's fallback path will use.
It gives PD 0.0029 for the shared demo and 0.0048 when the buyer has not confirmed (variant V3).
"""

from __future__ import annotations

import math

from app.profiles import MISSING, BuyerProfile

MODEL_VERSION = "scorecard-fallback"

# Placeholder coefficients (brief prompt 2). They are model parameters, not policy thresholds.
_INTERCEPT = -5.6
_W_TIER = 0.6
_W_LATE = 3.0
_W_TENOR = 0.005
_W_CONFIRMED = -0.5
_TIER_ORD = {"A": 0, "B": 1, "C": 2, "D": 3}

# Placeholder-only imputation: a buyer with no tier is scored as tier C, a missing late-payment rate takes
# a fixed value per tier, and a missing confirmation counts as not confirmed.
_IMPUTE_TIER = "C"
_IMPUTE_LATE_RATE = {"A": 0.03, "B": 0.08, "C": 0.15, "D": 0.30}


def predict_pd(buyer: BuyerProfile, tenor_days: int) -> float:
    """Calibrated-looking PD over the tenor, rounded to 6 decimal places."""
    tier = _IMPUTE_TIER if buyer.credit_tier is MISSING else buyer.credit_tier
    late = _IMPUTE_LATE_RATE[tier] if buyer.late_payment_rate is MISSING else float(buyer.late_payment_rate)
    confirmed = 1.0 if buyer.confirmed is True else 0.0
    logit = _INTERCEPT + _W_TIER * _TIER_ORD[tier] + _W_LATE * late + _W_TENOR * tenor_days
    logit += _W_CONFIRMED * confirmed
    return round(1.0 / (1.0 + math.exp(-logit)), 6)
