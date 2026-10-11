"""Wallet-local money helpers. Owner: Agent AI engineer.

Shared conversions (fee_rate_30d_to_apr, to_units, from_units) stay in shared/money.py, owned by the PM.
"""

import math
from decimal import Decimal


def apr_to_bps(apr: Decimal | str) -> int:
    """APR as basis points, rounded UP so a rounding step can never slip under a cap (CLAUDE.md 6.4).

    0.1095 -> 1095, 0.10951 -> 1096, 0.12 -> 1200.
    """
    value = Decimal(str(apr))
    if value < 0:
        raise ValueError(f"negative APR: {apr}")
    return math.ceil(value * 10_000)
