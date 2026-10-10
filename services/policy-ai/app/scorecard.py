"""The logistic-regression scorecard as plain JSON maths (model/scorecard.json). No numpy, no sklearn.

logit(PD) = intercept + sum(coef_i x (x_i - mean_i) / scale_i)
points    = offset - factor x logit(PD)
factor    = pdo / ln 2, offset = base_score - factor x ln(base_odds)
(600 points at 50:1 good:bad odds, 20 points to double the odds.)
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def contributions(card: Mapping[str, Any], values: Mapping[str, float]) -> dict[str, float]:
    """Each feature's share of the logit: coef x standardised value (0 at the training mean)."""
    return {
        name: card["coefficients"][name] * (values[name] - card["means"][name]) / card["scales"][name]
        for name in card["features"]
    }


def logit(card: Mapping[str, Any], values: Mapping[str, float]) -> float:
    return card["intercept"] + sum(contributions(card, values).values())


def predict_pd(card: Mapping[str, Any], values: Mapping[str, float]) -> float:
    return sigmoid(logit(card, values))


def scaling(card: Mapping[str, Any]) -> tuple[float, float]:
    """(factor, offset) of the points scale."""
    pts = card["points"]
    factor = pts["pdo"] / math.log(2)
    return factor, pts["base_score"] - factor * math.log(pts["base_odds"])


def score(card: Mapping[str, Any], values: Mapping[str, float]) -> float:
    """Scorecard points: base points plus points per unit of each feature."""
    pts = card["points"]
    return pts["base_points"] + sum(pts["per_unit"][name] * values[name] for name in card["features"])


def pd_from_score(card: Mapping[str, Any], points: float) -> float:
    factor, offset = scaling(card)
    return sigmoid((offset - points) / factor)
