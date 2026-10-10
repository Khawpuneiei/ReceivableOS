import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.profiles import MISSING, normalise_buyer, normalise_supplier, rating_to_tier

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE = json.loads((REPO_ROOT / "services/orchestrator/samples/profiles.json").read_text(encoding="utf-8"))


def test_orchestrator_sample_buyer():
    b = normalise_buyer(SAMPLE["buyer_profile"])
    assert b.credit_tier == "A"  # internal_rating A-
    assert b.late_payment_rate == Decimal("0.03")  # 1 - on_time_payment_rate 0.97, exact in Decimal
    assert b.avg_days_late == Decimal("1.5")
    assert b.confirmed is True
    assert b.relationship_months == 36
    assert b.sector == "retail"
    assert b.current_exposure == Decimal("0.00")
    assert b.buyer_limit == Decimal("10000000.00")


def test_orchestrator_sample_supplier():
    s = normalise_supplier(SAMPLE["supplier_profile"])
    assert s.on_time_ratio == Decimal(34) / Decimal(36)  # paid_on_time / invoices_total
    assert s.years_in_business == Decimal(3)  # years_trading
    assert s.invoices_financed_count == 12
    assert s.historical_default_rate == Decimal("0.0")
    assert s.dilution_rate == Decimal("0.02")
    assert s.kyc_valid is True
    assert s.kyc_expiry == date(2027, 6, 30)
    assert s.facility_limit == Decimal("3000000.00")
    assert s.current_exposure == Decimal("0.00")


def test_supplier_aliases():
    s = normalise_supplier(
        {
            "years_in_business": 7,
            "dispute_rate": "0.04",
            "supplier_limit": "2500000.00",
            "on_time_ratio": 0.9,
            "kyb_status": "VALID",
            "kyb_expires_at": "2027-01-31T00:00:00+07:00",
        }
    )
    assert s.years_in_business == Decimal(7)
    assert s.dilution_rate == Decimal("0.04")
    assert s.facility_limit == Decimal("2500000.00")
    assert s.on_time_ratio == Decimal("0.9")
    assert s.kyc_valid is True
    assert s.kyc_expiry == date(2027, 1, 31)
    assert normalise_supplier({"kyb_status": "EXPIRED"}).kyc_valid is False


def test_first_key_wins():
    s = normalise_supplier(
        {"years_in_business": 5, "years_trading": 9, "dilution_rate": 0.01, "dispute_rate": 0.2}
    )
    assert s.years_in_business == Decimal(5)
    assert s.dilution_rate == Decimal("0.01")
    b = normalise_buyer({"credit_tier": "b", "internal_rating": "AAA", "late_payment_rate": 0.1})
    assert b.credit_tier == "B"
    assert b.late_payment_rate == Decimal("0.1")


def test_buyer_acknowledged_alias():
    assert normalise_buyer({"buyer_acknowledged": True}).confirmed is True
    assert normalise_buyer({"buyer_confirmed": False, "buyer_acknowledged": True}).confirmed is False


@pytest.mark.parametrize(
    ("rating", "tier"),
    [
        ("AAA", "A"),
        ("A-", "A"),
        ("BBB", "B"),
        ("BBB-", "B"),
        ("BB+", "C"),
        ("BB-", "C"),
        ("B+", "D"),
        ("CCC", "D"),
    ],
)
def test_rating_to_tier(rating, tier):
    assert rating_to_tier(rating) == tier
    assert normalise_buyer({"credit_rating": rating}).credit_tier == tier


def test_unknown_rating_is_missing():
    assert rating_to_tier("excellent") is MISSING
    assert normalise_buyer({"internal_rating": "Z9"}).credit_tier is MISSING


def test_empty_profiles_are_missing_never_guessed():
    s = normalise_supplier({})
    assert s.years_in_business is MISSING
    assert s.invoices_financed_count is MISSING
    assert s.historical_default_rate is MISSING
    assert s.dilution_rate is MISSING
    assert s.on_time_ratio is MISSING
    assert s.kyc_valid is MISSING
    assert s.kyc_expiry is MISSING
    assert s.facility_limit is MISSING
    assert s.current_exposure == Decimal("0.00")  # brief 5.3: missing exposure counts as 0

    b = normalise_buyer(None)
    assert b.credit_tier is MISSING
    assert b.late_payment_rate is MISSING
    assert b.avg_days_late is MISSING
    assert b.confirmed is MISSING
    assert b.buyer_limit is MISSING
    assert b.relationship_months == 0
    assert b.current_exposure == Decimal("0.00")
    assert b.sector == "other"


def test_none_and_empty_string_count_as_missing():
    assert normalise_supplier({"dilution_rate": None, "dispute_rate": ""}).dilution_rate is MISSING
    assert normalise_supplier({"paid_on_time": 3, "invoices_total": 0}).on_time_ratio is MISSING


def test_invalid_explicit_tier_raises():
    with pytest.raises(ValueError, match="credit_tier"):
        normalise_buyer({"credit_tier": "Z"})


@pytest.mark.parametrize(
    "profile",
    [
        {"dilution_rate": "lots"},
        {"dilution_rate": 1.5},
        {"historical_default_rate": -0.1},
        {"invoices_financed_count": 2.5},
        {"current_exposure": True},
        {"facility_limit": "NaN"},
        {"kyc_valid": "maybe"},
        {"kyc_expiry": "30/09/2026"},
        {"paid_on_time": 40, "invoices_total": 36},
    ],
)
def test_malformed_supplier_values_raise(profile):
    with pytest.raises(ValueError):
        normalise_supplier(profile)


@pytest.mark.parametrize(
    "profile",
    [
        {"on_time_payment_rate": 1.2},
        {"avg_days_late": -1},
        {"buyer_confirmed": 1},
        {"relationship_months": "x"},
    ],
)
def test_malformed_buyer_values_raise(profile):
    with pytest.raises(ValueError):
        normalise_buyer(profile)
