"""Shared money helpers. Owner: PM.

policy-ai quotes fee_rate per 30 days; lender quotes and the wallet guard compare APR.
Both conversions use simple interest on a 365-day year: APR = fee_rate_30d * 365 / 30.
"""

from decimal import ROUND_HALF_UP, Decimal

DAYS_PER_YEAR = Decimal("365")
FEE_PERIOD_DAYS = Decimal("30")


def fee_rate_30d_to_apr(fee_rate_30d: Decimal) -> Decimal:
    """0.009 per 30 days -> 0.1095 APR."""
    return (Decimal(fee_rate_30d) * DAYS_PER_YEAR / FEE_PERIOD_DAYS).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def apr_to_fee_rate_30d(apr: Decimal) -> Decimal:
    """0.1095 APR -> 0.009 per 30 days."""
    return (Decimal(apr) * FEE_PERIOD_DAYS / DAYS_PER_YEAR).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
