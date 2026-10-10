from decimal import Decimal

import pytest

from app.money import apr_to_bps
from shared.money import fee_rate_30d_to_apr


@pytest.mark.parametrize(
    ("apr", "bps"),
    [
        ("0", 0),
        ("0.1095", 1095),
        ("0.10951", 1096),  # any fraction of a basis point rounds up
        ("0.12", 1200),
        ("0.12000001", 1201),  # a hair above the cap is never 1200
        ("0.195", 1950),  # V5: 19.5% APR
    ],
)
def test_apr_to_bps_rounds_up(apr, bps):
    assert apr_to_bps(Decimal(apr)) == bps


def test_apr_to_bps_rejects_negative():
    with pytest.raises(ValueError):
        apr_to_bps(Decimal("-0.01"))


def test_demo_lender_quotes_against_the_12_percent_cap():
    # Lender A: 0.90% per 30 days = 10.95% APR, under the 12% cap
    apr_a = fee_rate_30d_to_apr(Decimal("0.009"))
    assert apr_a == Decimal("0.1095")
    assert apr_to_bps(apr_a) == 1095
    # Lender B: 0.75% per 30 days = 9.13% APR
    assert apr_to_bps(fee_rate_30d_to_apr(Decimal("0.0075"))) == 913
