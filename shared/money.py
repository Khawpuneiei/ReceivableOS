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


# --- Token units: decimal-string amounts <-> on-chain integers ---
# tTHB has 2 decimals: "524300.00" THB <-> 52430000 units. Every chain call converts through these two
# functions, so the decimals live in one place and a 100x error cannot creep in.

TOKEN_DECIMALS = 2


def to_units(amount: Decimal | str, decimals: int = TOKEN_DECIMALS) -> int:
    """'524300.00' -> 52430000. Rejects negatives and more precision than the token has."""
    value = Decimal(str(amount))
    if value < 0:
        raise ValueError(f"negative amount: {amount}")
    scaled = value.scaleb(decimals)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{amount} has more than {decimals} decimal places")
    return int(scaled)


def from_units(units: int, decimals: int = TOKEN_DECIMALS) -> Decimal:
    """52430000 -> Decimal('524300.00')."""
    if units < 0:
        raise ValueError(f"negative units: {units}")
    return Decimal(units).scaleb(-decimals).quantize(Decimal(1).scaleb(-decimals))
