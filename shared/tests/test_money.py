from decimal import Decimal

import pytest

from shared.money import apr_to_fee_rate_30d, fee_rate_30d_to_apr, from_units, to_units


def test_demo_fee_rate_is_10_95_percent_apr():
    assert fee_rate_30d_to_apr(Decimal("0.009")) == Decimal("0.1095")


def test_round_trip():
    assert apr_to_fee_rate_30d(Decimal("0.1095")) == Decimal("0.009000")


def test_demo_draw_to_units_and_back():
    assert to_units("524300.00") == 52430000
    assert from_units(52430000) == Decimal("524300.00")
    assert str(from_units(52430000)) == "524300.00"


def test_to_units_rejects_extra_precision_and_negatives():
    for bad in ("1.005", "-1.00"):
        with pytest.raises(ValueError):
            to_units(bad)


def test_other_decimals():
    assert to_units("1.5", decimals=6) == 1500000
    assert from_units(1500000, decimals=6) == Decimal("1.500000")
