"""Fictional invoice sequences for related-party checks: self-invoicing and round-trip invoices.

Run directly to write ``data/invoices/demo/09_self_invoice.pdf``.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf  # noqa: E402

BASE = SHOWCASE_PROFILES[0]
# The buyer billing the supplier back: roles and tax IDs swapped, its own bank account.
REVERSE = {
    "supplier": BASE["buyer"],
    "supplier_id": BASE["buyer_id"],
    "supplier_address": BASE["buyer_address"],
    "supplier_contact": BASE["buyer_contact"],
    "buyer": BASE["supplier"],
    "buyer_id": BASE["supplier_id"],
    "buyer_address": BASE["supplier_address"],
    "buyer_contact": BASE["supplier_contact"],
    "brand": "MEKONG BASKET",
    "bank_account": "300-400-5002",
}
SELF = {"buyer": "Siam Fresh Pack (Branch 0001)", "buyer_id": BASE["supplier_id"]}


def invoice(quantity: int, invoice_no: str, issue_date: str, *, reverse=False, self_billed=False) -> bytes:
    subtotal = Decimal(quantity) * Decimal("14.00")
    tax = (subtotal * Decimal("0.07")).quantize(Decimal("0.01"))
    profile = {
        **BASE,
        **(REVERSE if reverse else {}),
        **(SELF if self_billed else {}),
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


# name -> (earlier invoices as (quantity, issue date, reverse?), final invoice kwargs, expected flag or None)
CASES = {
    "single_invoice": ((), {}, None),
    "self_invoice": ((), {"self_billed": True}, "SUPPLIER_IS_BUYER"),
    "round_trip": (((49_500, "2026-09-15", True),), {}, "circular_invoicing"),
    "reciprocal_small_purchase": (((8_000, "2026-09-15", True),), {}, None),
    "reverse_outside_window": (((50_000, "2026-05-01", True),), {}, None),
    "repeat_same_direction": (((50_000, "2026-09-01", False),), {}, None),
}


def main() -> None:
    from datagen.generate import DATA

    path = DATA / "demo" / "09_self_invoice.pdf"
    # The buyer carries the supplier's own tax ID: a company billing itself.
    path.write_bytes(invoice(50_000, "SFP-INV-2026-0149", "2026-10-01", self_billed=True))
    print(path)


if __name__ == "__main__":
    main()
