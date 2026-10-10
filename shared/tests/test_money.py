from decimal import Decimal

from shared.money import apr_to_fee_rate_30d, fee_rate_30d_to_apr


def test_demo_fee_rate_is_10_95_percent_apr():
    assert fee_rate_30d_to_apr(Decimal("0.009")) == Decimal("0.1095")


def test_round_trip():
    assert apr_to_fee_rate_30d(Decimal("0.1095")) == Decimal("0.009000")
