"""Exact evaluation of already-canonical values, independent of optional model experiments."""

import re
from decimal import Decimal

FIELDS = ("document_number", "amount", "currency", "issue_date", "due_date", "supplier_name", "buyer_name")


def matches(observed, truth):
    result = {}
    for field in FIELDS:
        actual, expected = observed.get(field), truth[field]
        if field == "amount" and actual is not None and expected is not None:
            try:
                result[field] = bool(re.fullmatch(r"\d+(?:\.\d+)?", actual)) and Decimal(actual) == Decimal(
                    expected
                )
            except (ValueError, ArithmeticError):
                result[field] = False
        else:
            result[field] = actual == expected
    return result
