"""Probability of default (PD) for the credit decision (services/policy-ai/CLAUDE.md sections 8.6, 9).

The model is loaded once at import from POLICY_MODEL_DIR (default services/policy-ai/model). The fallback
chain never lets the endpoint fail:
  1. the model model_card.json selects: the LR scorecard (scorecard.json, pure JSON maths) or LightGBM
     (lgbm.txt + calibrator.json, needs the optional lightgbm package);
  2. if that can't load (LightGBM not installed, a missing or corrupt file): scorecard.json, reported as
     model_version "scorecard-fallback";
  3. if that can't load either: the fixed placeholder formula, "placeholder-fallback".
A failure while scoring one request also drops to the placeholder for that request (logged, never a 500).
Scoring is deterministic and local: no network, no LLM. Files are read as JSON or LightGBM text; nothing
is unpickled.
"""

from __future__ import annotations

import bisect
import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app import scorecard
from app.features import FEATURES, FeatureVector, build_features
from app.profiles import MISSING, TIERS

log = logging.getLogger("policy-ai")

DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[1] / "model"
MODEL_DIR_ENV = "POLICY_MODEL_DIR"
SCORECARD_FALLBACK = "scorecard-fallback"
PLACEHOLDER_VERSION = "placeholder-fallback"
TOP_DRIVERS = 3
PD_DECIMALS = 6


@dataclass(frozen=True)
class Driver:
    """One feature's push on the PD in log-odds, relative to the average training invoice (> 0 raises it)."""

    feature: str
    value: float | None  # None when the profile left it out and a tier median was used
    contribution: float


@dataclass(frozen=True)
class Prediction:
    pd: float
    version: str
    drivers: tuple[Driver, ...] = ()


class Scorer(Protocol):
    version: str

    def predict(self, ctx: Any) -> Prediction: ...


def _top(fv: FeatureVector, contributions: dict[str, float], version: str, pd: float) -> Prediction:
    ranked = sorted(
        (name for name in FEATURES if contributions.get(name)), key=lambda n: (-abs(contributions[n]), n)
    )
    drivers = tuple(
        Driver(name, None if name in fv.imputed else fv.values[name], round(contributions[name], 4))
        for name in ranked[:TOP_DRIVERS]
    )
    return Prediction(round(pd, PD_DECIMALS), version, drivers)


def _features(ctx: Any, medians: dict) -> FeatureVector:
    return build_features(ctx.invoice, ctx.supplier, ctx.buyer, ctx.as_of, medians)


class ScorecardModel:
    """The logistic-regression scorecard from scorecard.json."""

    def __init__(self, card: dict, version: str):
        if card.get("features") != list(FEATURES):
            raise ValueError("scorecard features don't match app.features")
        self.card, self.version = card, version

    def predict(self, ctx: Any) -> Prediction:
        fv = _features(ctx, self.card["medians"])
        contributions = scorecard.contributions(self.card, fv.values)
        pd = scorecard.sigmoid(self.card["intercept"] + sum(contributions.values()))
        return _top(fv, contributions, self.version, pd)


def calibrate(calibrator: dict, margin: float) -> float:
    """Platt or isotonic (clipped linear interpolation, as numpy.interp), from calibrator.json."""
    if calibrator["method"] == "platt":
        return scorecard.sigmoid(calibrator["a"] * margin + calibrator["b"])
    xs, ys = calibrator["x"], calibrator["y"]
    if margin <= xs[0]:
        return ys[0]
    if margin >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_right(xs, margin)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (margin - x0) / (x1 - x0)


class LightGBMModel:
    """LightGBM text model plus its JSON calibrator. Needs the optional lightgbm package."""

    def __init__(self, model_dir: Path, card: dict, version: str):
        import lightgbm  # optional: ImportError moves the chain to the scorecard

        self.booster = lightgbm.Booster(model_file=str(model_dir / "lgbm.txt"))
        if self.booster.feature_name() != list(FEATURES):
            raise ValueError("lgbm.txt features don't match app.features")
        self.calibrator = json.loads((model_dir / "calibrator.json").read_text(encoding="utf-8"))
        self.medians, self.version = card["medians"], version

    def predict(self, ctx: Any) -> Prediction:
        fv = _features(ctx, self.medians)
        row = [fv.row()]
        margin = float(self.booster.predict(row, raw_score=True)[0])
        contrib = self.booster.predict(row, pred_contrib=True)[0]  # TreeSHAP, last value = bias
        contributions = {name: float(c) for name, c in zip(FEATURES, contrib, strict=False)}
        return _top(fv, contributions, self.version, calibrate(self.calibrator, margin))


class PlaceholderModel:
    """The fixed formula used before training existed (brief prompt 2). Last resort only.

    logit = -5.6 + 0.6 x tier_ord + 3.0 x late_payment_rate + 0.005 x tenor_days - 0.5 x confirmed;
    a buyer with no tier is scored as C, a missing late rate takes a fixed value per tier.
    """

    version = PLACEHOLDER_VERSION
    _INTERCEPT, _W_TIER, _W_LATE, _W_TENOR, _W_CONFIRMED = -5.6, 0.6, 3.0, 0.005, -0.5
    _IMPUTE_TIER = "C"
    _IMPUTE_LATE_RATE = {"A": 0.03, "B": 0.08, "C": 0.15, "D": 0.30}

    def predict(self, ctx: Any) -> Prediction:
        buyer = ctx.buyer
        tier = self._IMPUTE_TIER if buyer.credit_tier is MISSING else buyer.credit_tier
        late = (
            self._IMPUTE_LATE_RATE[tier]
            if buyer.late_payment_rate is MISSING
            else float(buyer.late_payment_rate)
        )
        confirmed = 1.0 if buyer.confirmed is True else 0.0
        logit = self._INTERCEPT + self._W_TIER * TIERS.index(tier) + self._W_LATE * late
        logit += self._W_TENOR * ctx.tenor_days + self._W_CONFIRMED * confirmed
        return Prediction(round(1.0 / (1.0 + math.exp(-logit)), PD_DECIMALS), self.version)


PLACEHOLDER = PlaceholderModel()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load(model_dir: str | Path | None = None) -> Scorer:
    """Walk the fallback chain and return the first model that loads."""
    model_dir = Path(model_dir or os.environ.get(MODEL_DIR_ENV) or DEFAULT_MODEL_DIR)
    try:
        card = _read_json(model_dir / "model_card.json")
        version, selected = card["version"], card["selected"]
        if selected == "lgbm":
            return LightGBMModel(model_dir, card, version)
        if selected == "lr":
            return ScorecardModel(_read_json(model_dir / "scorecard.json"), version)
        raise ValueError(f"unknown selected model {selected!r}")
    except Exception as exc:  # noqa: BLE001 - any load problem moves down the chain
        log.warning(
            "served model not loaded from %s (%s); trying the scorecard", model_dir, type(exc).__name__
        )
    try:
        return ScorecardModel(_read_json(model_dir / "scorecard.json"), SCORECARD_FALLBACK)
    except Exception as exc:  # noqa: BLE001
        log.warning("scorecard not loaded from %s (%s); using the placeholder", model_dir, type(exc).__name__)
    return PLACEHOLDER


_ACTIVE: Scorer = load()


def active() -> Scorer:
    return _ACTIVE


def predict(ctx: Any) -> Prediction:
    """PD for one request with the active model; the placeholder if scoring fails."""
    try:
        return _ACTIVE.predict(ctx)
    except Exception as exc:  # noqa: BLE001 - the decision must never fail on the model
        log.warning(
            "model %s failed to score (%s); using the placeholder", _ACTIVE.version, type(exc).__name__
        )
        return PLACEHOLDER.predict(ctx)


# --- Reason text for the top drivers: fixed labels and numbers only, never profile or invoice text ---

_LABELS: dict[str, tuple[str, str, str]] = {
    "buyer_tier_ord": ("BUYER_TIER", "Buyer tier", "tier"),
    "buyer_late_payment_rate": ("BUYER_LATE_RATE", "Buyer late-payment rate", "pct"),
    "buyer_avg_days_late": ("BUYER_DAYS_LATE", "Buyer average days late", "num"),
    "buyer_confirmed": ("BUYER_CONFIRMED", "Buyer", "confirmed"),
    "log1p_relationship_months": ("RELATIONSHIP", "Months of relationship with the buyer", "count"),
    "log1p_supplier_years_in_business": ("SELLER_YEARS", "Seller years in business", "count"),
    "log1p_supplier_invoices_financed_count": ("SELLER_HISTORY", "Invoices financed before", "count"),
    "supplier_historical_default_rate": ("SELLER_DEFAULTS", "Seller historical default rate", "pct"),
    "supplier_dilution_rate": ("SELLER_DILUTION", "Seller dilution rate", "pct"),
    "supplier_on_time_ratio": ("SELLER_ON_TIME", "Seller on-time ratio", "pct"),
    "log_amount": ("AMOUNT", "Invoice amount", "money"),
    "tenor_days": ("TENOR", "Tenor in days", "int"),
    "invoice_age_days": ("INVOICE_AGE", "Invoice age in days", "int"),
    "amount_to_buyer_limit": ("BUYER_LIMIT_USE", "Invoice amount / buyer limit", "pct"),
    "ocr_confidence": ("OCR_CONFIDENCE", "OCR confidence", "num"),
    "fraud_score": ("FRAUD_SCORE", "OCR fraud score", "num"),
    "buyer_tier_x_tenor_30d": ("TIER_X_TENOR", "Buyer tier rank x tenor in months", "num"),
}


def _display(kind: str, value: float) -> str:
    if kind == "tier":
        return TIERS[int(round(value))]
    if kind == "pct":
        return f"{value:.2%}"
    if kind == "confirmed":
        return "confirmed the invoice" if value >= 1 else "has not confirmed the invoice"
    if kind == "count":
        return str(int(round(math.expm1(value))))
    if kind == "money":
        return f"{math.exp(value):,.2f}"
    if kind == "int":
        return str(int(round(value)))
    return f"{value:.4g}"


def describe(driver: Driver) -> tuple[str, str]:
    """(reason code, message) for one driver, e.g. ("MODEL.BUYER_TIER", "Buyer tier A lowers ...")."""
    direction = "raises" if driver.contribution > 0 else "lowers"
    if driver.feature.startswith("sector_"):
        sector = driver.feature.removeprefix("sector_")
        state = "is" if driver.value else "is not"
        return "MODEL.SECTOR", f"Buyer sector {state} {sector}: {direction} predicted default"
    code, label, kind = _LABELS[driver.feature]
    shown = "not given (tier median used)" if driver.value is None else _display(kind, driver.value)
    return f"MODEL.{code}", f"{label} {shown}: {direction} predicted default"
