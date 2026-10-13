"""Fictional invoices that print the total in words, honestly or after the digits were regenerated.

A "regenerated" invoice is internally consistent (lines, subtotal, VAT and total all agree) at a
new amount, but its amount-in-words line still states the original total: the case arithmetic
checks cannot see. Run directly to write ``data/invoices/demo/07_words_mismatch.pdf``.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datagen.generate import DATA  # noqa: E402
from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf  # noqa: E402

from app.amount_words import thai_baht_text  # noqa: E402

THAI_FONT = DATA / "fonts" / "NotoSansThai-Regular.ttf"
ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen"
).split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def english_words(value: int) -> str:
    """749000 -> 'Seven Hundred Forty-Nine Thousand' (invoice "amount in words" style)."""

    def below_thousand(number: int) -> list[str]:
        hundreds, rest = divmod(number, 100)
        words = [ONES[hundreds], "hundred"] if hundreds else []
        if rest >= 20:
            words.append(TENS[rest // 10] + (f"-{ONES[rest % 10]}" if rest % 10 else ""))
        elif rest:
            words.append(ONES[rest])
        return words

    words: list[str] = []
    for scale, name in ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand"), (1, "")):
        chunk, value = divmod(value, scale)
        if chunk:
            words += below_thousand(chunk) + ([name] if name else [])
    return " ".join(words or ["zero"]).title()


def invoice(quantity: int, written_total: Decimal | None, invoice_no: str, *, thai: bool = True) -> bytes:
    """Showcase invoice for ``quantity`` trays at 14.00 + 7% VAT, with ``written_total`` in words."""
    subtotal = Decimal(quantity) * Decimal("14.00")
    tax = (subtotal * Decimal("0.07")).quantize(Decimal("0.01"))
    total = subtotal + tax
    profile = {
        **SHOWCASE_PROFILES[0],
        "invoice_no": invoice_no,
        "subtotal": f"{subtotal:.2f}",
        "tax": f"{tax:.2f}",
        "total": f"{total:.2f}",
        "lines": (("TRAY-01", "Food trays", str(quantity), "EA", "14.00", f"{subtotal:.2f}"),),
    }
    content = build_pdf(profile)
    written_total = total if written_total is None else written_total
    baht, satang = divmod(int(written_total * 100), 100)
    english = f"Amount in words: {english_words(baht)} Baht"
    english += f" and {english_words(satang)} Satang Only" if satang else " Only"
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        page = doc[0]
        page.insert_text((40, 500), english, fontsize=7.5, fontname="helv")
        if thai:
            page.insert_font(fontname="noto-thai", fontfile=str(THAI_FONT))
            page.insert_text((40, 516), thai_baht_text(written_total), fontsize=8, fontname="noto-thai")
        return doc.tobytes(deflate=True, no_new_id=True)


# name -> (quantity printed in digits, total written in words or None for "same as digits", expect flag)
CASES = {
    "honest_749000": (50_000, None, False),
    "honest_satang": (12_345, None, False),
    "honest_million": (100_000, None, False),
    "honest_small": (7, None, False),
    "regenerated_up_10pct": (55_000, Decimal("749000.00"), True),
    "regenerated_transposed": (53_000, Decimal("749000.00"), True),
    "regenerated_double": (100_000, Decimal("749000.00"), True),
    "words_off_by_one_satang": (12_345, Decimal("184928.11"), True),
}


def case_pdf(name: str, invoice_no: str) -> bytes:
    quantity, written, _ = CASES[name]
    return invoice(quantity, written, invoice_no)


def main() -> None:
    path = DATA / "demo" / "07_words_mismatch.pdf"
    # Digits regenerated to 823,900.00 (55,000 trays); the words still say 749,000 baht.
    path.write_bytes(invoice(55_000, Decimal("749000.00"), "SFP-INV-2026-0147"))
    print(path)


if __name__ == "__main__":
    main()
