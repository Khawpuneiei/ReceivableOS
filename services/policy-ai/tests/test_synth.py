"""The seeded synthetic invoice generator (training/synth.py, brief section 8.3). Runs on N = 2,000."""

import hashlib
import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("pandas")

from factories import BUYER, INVOICE, SUPPLIER  # noqa: E402
from training import synth  # noqa: E402

from app.profiles import MISSING, TIERS, normalise_buyer, normalise_supplier  # noqa: E402

N = 2000
CFG = synth.load_config()


@pytest.fixture(scope="module")
def rows():
    return synth.generate(CFG, N)


def _latent_inputs(supplier: dict, buyer: dict, tenor_days: int = 34, age_days: int = 11) -> dict:
    """Latent-model inputs for the shared demo invoice, read through the service's profile normaliser."""
    s, b = normalise_supplier(supplier), normalise_buyer(buyer)
    return {
        "tier_ord": TIERS.index(b.credit_tier),
        "late_payment_rate": float(b.late_payment_rate),
        "avg_days_late": float(b.avg_days_late),
        "confirmed": 1.0 if b.confirmed is True else 0.0,
        "relationship_months": b.relationship_months,
        "years_in_business": float(s.years_in_business),
        "invoices_financed": s.invoices_financed_count,
        "historical_default_rate": float(s.historical_default_rate),
        "dilution_rate": float(s.dilution_rate),
        "on_time_ratio": float(s.on_time_ratio),
        "amount": float(INVOICE["amount"]),
        "tenor_days": tenor_days,
        "invoice_age_days": age_days,
        "buyer_limit": float(b.buyer_limit),
        "ocr_confidence": INVOICE["confidence"],
        "fraud_score": INVOICE["fraud_score"],
        "sector": b.sector,
    }


def test_same_seed_gives_a_byte_identical_csv(tmp_path):
    first = synth.write(synth.generate(CFG, N), tmp_path / "a.csv")
    again = synth.write(synth.generate(CFG, N), tmp_path / "b.csv")
    assert first == again == hashlib.sha256((tmp_path / "a.csv").read_bytes()).hexdigest()


def test_base_rate_is_plausible(rows):
    assert 0.02 <= rows["y"].mean() <= 0.08


def test_tier_shares_follow_the_config(rows):
    to_tier = {r: t for t, ratings in CFG["buyers"]["ratings"].items() for r in ratings}
    shares = rows["buyer.internal_rating"].map(to_tier).value_counts(normalize=True)
    for tier, target in CFG["buyers"]["tier_shares"].items():
        assert abs(shares[tier] - target) <= 0.03, tier


def test_riskier_tiers_default_more(rows):
    to_tier = {r: t for t, ratings in CFG["buyers"]["ratings"].items() for r in ratings}
    rates = rows.groupby(rows["buyer.internal_rating"].map(to_tier))["y"].mean()
    assert rates["A"] < rates["B"] < rates["C"] < rates["D"]


def test_late_rates_drift_up_in_the_last_cohorts(rows):
    drifted = rows["cohort"] > CFG["n_cohorts"] - CFG["drift"]["last_cohorts"]
    late = 1 - rows["buyer.on_time_payment_rate"]
    by_buyer = late.groupby([rows["buyer_id"], drifted]).mean().unstack().dropna()
    ratio = (by_buyer[True] / by_buyer[False]).replace([np.inf], np.nan).dropna().median()
    assert ratio == pytest.approx(CFG["drift"]["late_rate_multiplier"], abs=0.02)


def test_every_row_normalises_through_the_service_profiles(rows):
    for row in rows.to_dict("records"):
        invoice, supplier, buyer, as_of = synth.profiles(row)
        s, b = normalise_supplier(supplier), normalise_buyer(buyer)
        assert b.credit_tier is not MISSING and s.on_time_ratio is not MISSING
        assert invoice["due_date"] >= invoice["issue_date"] and as_of.isoformat() >= invoice["issue_date"]


def test_missing_keys_are_left_out_of_the_profile(rows):
    with_gap = rows[rows["buyer.avg_days_late"].isna()].iloc[0].to_dict()
    assert "avg_days_late" not in synth.profiles(with_gap)[2]


def test_demo_profiles_sit_inside_the_pricing_windows():
    """Latent PDs the fee depends on (plan C20): demo fee 0.009, V3 fee 0.012, scenario 8 still approved."""
    demo = synth.latent_pd(_latent_inputs(SUPPLIER, BUYER), CFG)
    v3 = synth.latent_pd(_latent_inputs(SUPPLIER, {**BUYER, "buyer_confirmed": False}), CFG)
    s8_supplier = {**SUPPLIER, "invoices_total": 37, "paid_on_time": 34, "dilution_rate": 0.07}
    s8 = synth.latent_pd(_latent_inputs(s8_supplier, BUYER), CFG)
    assert demo <= 0.00347
    assert 0.0036 < v3 <= 0.0058
    assert s8 <= 0.0057
    noise = math.exp(CFG["latent"]["noise_sd"] ** 2 / 2)  # averaging the label noise in raises p ~4.6%
    assert demo * noise <= 0.00347
