"""Fictional invoice sequences between one supplier and buyer, with and without an amount spike."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf  # noqa: E402

OTHER_BUYER = {"buyer": "Example Harbour Foods PCL", "buyer_id": "0105561000003"}


def invoice(quantity: int, invoice_no: str, issue_date: str, *, other_buyer: bool = False) -> bytes:
    """Showcase invoice for ``quantity`` trays at 14.00 + 7% VAT; every printed figure agrees."""
    subtotal = Decimal(quantity) * Decimal("14.00")
    tax = (subtotal * Decimal("0.07")).quantize(Decimal("0.01"))
    profile = {
        **SHOWCASE_PROFILES[0],
        **(OTHER_BUYER if other_buyer else {}),
        "invoice_no": invoice_no,
        "issue_date": issue_date,
        "due_date": "2026-11-15",
        "terms": "Per agreement",
        "subtotal": f"{subtotal:.2f}",
        "tax": f"{tax:.2f}",
        "total": f"{subtotal + tax:.2f}",
        "lines": (("TRAY-01", "Food trays", str(quantity), "EA", "14.00", f"{subtotal:.2f}"),),
    }
    return build_pdf(profile)


# Four ordinary monthly invoices (roughly 0.67m-0.83m THB) build the pair's history first.
HISTORY = ((45_000, "2026-06-01"), (52_000, "2026-07-01"), (50_000, "2026-08-01"), (55_000, "2026-09-01"))
# name -> (quantity, other buyer?, expect amount_outlier); each runs against HISTORY only.
CASES = {
    "ordinary_next_month": (51_000, False, False),
    "double_order": (100_000, False, False),
    "spike_3x": (160_000, False, True),
    "spike_10x": (500_000, False, True),
    "spike_other_buyer_no_history": (160_000, True, False),
}
