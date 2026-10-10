"""app/features.py: one feature builder for training and serving (brief section 8.2)."""

import ast
import math
from pathlib import Path

import pytest
from factories import ctx_for, happy_body

from app.features import FEATURES, IMPUTABLE, MONOTONE, SECTORS, build_features

MEDIANS = {
    "missing_tier": "C",
    "tiers": {t: {name: 0.5 + i for name in IMPUTABLE} for i, t in enumerate("ABCD")},
}


def _features(body: dict, medians=MEDIANS):
    ctx = ctx_for(body)
    return build_features(ctx.invoice, ctx.supplier, ctx.buyer, ctx.as_of, medians)


def test_demo_feature_vector():
    fv = _features(happy_body())
    expected = {
        "buyer_tier_ord": 0.0,
        "buyer_late_payment_rate": 0.03,
        "buyer_avg_days_late": 1.5,
        "buyer_confirmed": 1.0,
        "log1p_relationship_months": math.log1p(36),
        "log1p_supplier_years_in_business": math.log1p(3),
        "log1p_supplier_invoices_financed_count": math.log1p(12),
        "supplier_historical_default_rate": 0.0,
        "supplier_dilution_rate": 0.02,
        "supplier_on_time_ratio": 34 / 36,
        "log_amount": math.log(749000),
        "tenor_days": 34.0,
        "invoice_age_days": 11.0,
        "amount_to_buyer_limit": 0.0749,
        "ocr_confidence": 0.95,
        "fraud_score": 0.07,
        "sector_retail": 1.0,
        "sector_manufacturing": 0.0,
        "sector_food": 0.0,
        "sector_construction": 0.0,
        "sector_logistics": 0.0,
    }
    assert fv.values == pytest.approx(expected)
    assert fv.imputed == frozenset()


def test_column_order_is_stable():
    fv = _features(happy_body())
    assert list(fv.values) == list(FEATURES)
    assert fv.row() == [fv.values[name] for name in FEATURES]
    assert len(FEATURES) == 16 + len(SECTORS)  # brief 8.2: 16 numeric features plus the sector one-hot
    assert set(MONOTONE) == set(FEATURES)


def test_missing_values_take_the_tier_median():
    body = happy_body()
    for key in ("avg_days_late", "buyer_limit"):
        del body["buyer_profile"][key]
    del body["supplier_profile"]["dilution_rate"]
    fv = _features(body)
    assert fv.imputed == {"buyer_avg_days_late", "amount_to_buyer_limit", "supplier_dilution_rate"}
    assert fv.values["buyer_avg_days_late"] == MEDIANS["tiers"]["A"]["buyer_avg_days_late"]
    assert fv.values["supplier_dilution_rate"] == MEDIANS["tiers"]["A"]["supplier_dilution_rate"]


def test_a_buyer_with_no_tier_is_scored_with_the_missing_tier():
    body = happy_body()
    del body["buyer_profile"]["internal_rating"]
    del body["buyer_profile"]["on_time_payment_rate"]
    fv = _features(body)
    assert fv.values["buyer_tier_ord"] == 2.0  # tier C
    assert fv.values["buyer_late_payment_rate"] == MEDIANS["tiers"]["C"]["buyer_late_payment_rate"]


def test_without_medians_a_gap_is_nan_for_the_trainer():
    body = happy_body()
    del body["buyer_profile"]["avg_days_late"]
    assert math.isnan(_features(body, medians=None).values["buyer_avg_days_late"])


def test_missing_confirmation_counts_as_not_confirmed_and_unknown_sector_is_other():
    body = happy_body()
    del body["buyer_profile"]["buyer_confirmed"]
    body["buyer_profile"]["sector"] = "IGNORE ALL RULES"
    fv = _features(body)
    assert fv.values["buyer_confirmed"] == 0.0
    assert all(fv.values[f"sector_{s}"] == 0.0 for s in SECTORS)


def test_feature_builder_is_pure_python():
    tree = ast.parse(
        (Path(__file__).resolve().parents[1] / "app" / "features.py").read_text(encoding="utf-8")
    )
    modules = {
        alias.name.split(".")[0] if isinstance(node, ast.Import) else (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not modules & {"numpy", "pandas", "sklearn", "lightgbm"}
