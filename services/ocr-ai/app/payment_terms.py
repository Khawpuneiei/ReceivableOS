"""Check the printed payment terms against the issue and due dates.

"Net 45" on an invoice issued 1 October means due 15 November. A due date that disagrees
with the invoice's own terms changes the financing tenor (and the fee), and is a common sign
of a re-dated or edited invoice. Terms are document text: this module only reads a day count
and never treats the text as instructions.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
# Every pattern needs a payment word next to the day count, so "delivery within 7 days" or
# "please check within 7 days" never counts as terms.
TERMS = (
    re.compile(r"\bnet\s*[-:]?\s*(\d{1,3})\b(?!\s*(?:eom|end of month|th|st|nd|rd|%))", re.IGNORECASE),
    re.compile(
        r"\b(?:payment\s+terms?|credit\s+terms?|terms)\s*[:\-]?\s*(\d{1,3})\s*days?\b"
        r"(?!\s*(?:eom|end of month))",
        re.IGNORECASE,
    ),
    re.compile(r"\bpay(?:ment)?\s+(?:is\s+)?(?:due\s+)?within\s+(\d{1,3})\s*days\b", re.IGNORECASE),
    re.compile(r"(?:ชำระ(?:เงิน)?(?:ภายใน)?|เครดิต|เงื่อนไขการชำระเงิน\s*[:：]?)\s*(\d{1,3})\s*วัน"),
)
ON_RECEIPT = re.compile(
    r"\b(?:due\s+on\s+receipt|payable\s+on\s+receipt|cash\s+on\s+delivery)\b", re.IGNORECASE
)


def term_days(text: str) -> set[int]:
    """Every payment-term day count stated in ``text`` (0 for "due on receipt")."""
    # NFKC splits Thai SARA AM (ำ) into two marks; put it back so "ชำระ" still matches.
    text = unicodedata.normalize("NFKC", text).replace("\u0e4d\u0e32", "\u0e33").translate(THAI_DIGITS)
    days = {int(match.group(1)) for pattern in TERMS for match in pattern.finditer(text)}
    if ON_RECEIPT.search(text):
        days.add(0)
    return {value for value in days if value <= 365}


def payment_terms_reason(texts: list[str], issue: date | None, due: date | None) -> str | None:
    """``DUE_DATE_TERMS_MISMATCH`` when the only stated term disagrees with due - issue."""
    if issue is None or due is None:
        return None
    days = set().union(*(term_days(text) for text in texts)) if texts else set()
    if len(days) != 1:
        return None  # no terms, or several conflicting ones: nothing reliable to compare
    if issue + timedelta(days=days.pop()) != due:
        return "DUE_DATE_TERMS_MISMATCH"
    return None
