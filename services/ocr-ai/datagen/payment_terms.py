"""Fictional invoices whose printed payment terms agree, or not, with their issue and due dates.

Run directly to write ``data/invoices/demo/08_terms_mismatch.pdf``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datagen.generate import DATA  # noqa: E402
from datagen.reliability import draw  # noqa: E402
from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf  # noqa: E402

# name -> (English terms, Thai terms line or "", issue date, due date, expect DUE_DATE_TERMS_MISMATCH)
CASES = {
    "honest_net45": ("Net 45", "", "2026-10-01", "2026-11-15", False),
    "honest_net30": ("Net 30", "", "2026-10-01", "2026-10-31", False),
    "honest_on_receipt": ("Due on receipt", "", "2026-10-01", "2026-10-01", False),
    "honest_no_day_count": ("Per master agreement", "", "2026-10-01", "2026-12-31", False),
    "honest_end_of_month": ("Net 30 EOM", "", "2026-10-01", "2026-11-30", False),
    "honest_thai_credit": (
        "Per agreement",
        "เงื่อนไขการชำระเงิน: เครดิต 30 วัน",
        "2026-10-01",
        "2026-10-31",
        False,
    ),
    "due_extended": ("Net 45", "", "2026-10-01", "2026-12-31", True),
    "due_shortened": ("Net 45", "", "2026-10-01", "2026-10-20", True),
    "terms_edited": ("Net 30", "", "2026-10-01", "2026-11-15", True),
    "thai_credit_extended": (
        "Per agreement",
        "เงื่อนไขการชำระเงิน: เครดิต 30 วัน",
        "2026-10-01",
        "2026-11-30",
        True,
    ),
}


def invoice(terms: str, thai_terms: str, issue: str, due: str, invoice_no: str) -> bytes:
    profile = {
        **SHOWCASE_PROFILES[0],
        "terms": terms,
        "issue_date": issue,
        "due_date": due,
        "invoice_no": invoice_no,
    }
    content = build_pdf(profile)
    if not thai_terms:
        return content
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        draw(doc[0], (40, 516), thai_terms, "th")  # Thai runs in Noto Thai, digits and colon in Helvetica
        return doc.tobytes(deflate=True, no_new_id=True)


def case_pdf(name: str, invoice_no: str) -> bytes:
    terms, thai_terms, issue, due, _ = CASES[name]
    return invoice(terms, thai_terms, issue, due, invoice_no)


def main() -> None:
    path = DATA / "demo" / "08_terms_mismatch.pdf"
    # "Net 45" from 1 Oct means 15 Nov; the due date was pushed to 31 Dec.
    path.write_bytes(invoice("Net 45", "", "2026-10-01", "2026-12-31", "SFP-INV-2026-0148"))
    print(path)


if __name__ == "__main__":
    main()
