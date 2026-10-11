"""Conservative international normalization; ambiguous observations stay unresolved."""

import re
import unicodedata
from datetime import date
from decimal import Decimal

import pycountry
from babel.core import UnknownLocaleError
from babel.numbers import get_currency_precision, parse_decimal

from app.config import MAX_NUMERIC_DIGITS, MAX_NUMERIC_SCALE, MAX_NUMERIC_TEXT_CHARS


def normalize_currency(raw: str) -> str:
    code = raw.strip().upper()
    if pycountry.currencies.get(alpha_3=code) is None or code in {
        "XXX",
        "XTS",
        "XAU",
        "XAG",
        "XPD",
        "XPT",
        "XBA",
        "XBB",
        "XBC",
        "XBD",
        "XDR",
        "XSU",
        "XUA",
    }:
        raise ValueError("Currency requires an explicit supported ISO 4217 code")
    return code


def minor_unit(currency: str) -> Decimal:
    return Decimal(1).scaleb(-get_currency_precision(normalize_currency(currency)))


def normalize_number(raw: str, locale: str | None) -> Decimal:
    if len(raw) > MAX_NUMERIC_TEXT_CHARS or re.search(r"[eE]", raw):
        raise ValueError("Financial number size or notation is unsupported")
    text = "".join(str(unicodedata.decimal(char)) if char.isdecimal() else char for char in raw.strip())
    if locale:
        try:
            result = parse_decimal(text, locale=locale.replace("-", "_"), strict=True)
        except UnknownLocaleError as exc:
            raise ValueError("Unsupported source locale") from exc
    else:
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
            raise ValueError("Number separators require source locale evidence")
        if re.fullmatch(r"[+-]?\d{1,3}\.\d{3}", text):
            raise ValueError("Ambiguous decimal or grouping separator")
        result = Decimal(text)
    if not result.is_finite() or result < 0:
        raise ValueError("Financial numbers must be finite and nonnegative")
    if (
        len(result.as_tuple().digits) > MAX_NUMERIC_DIGITS
        or result.adjusted() >= MAX_NUMERIC_DIGITS
        or result.as_tuple().exponent < -MAX_NUMERIC_SCALE
    ):
        raise ValueError("Financial number precision exceeds supported bounds")
    return result


def normalize_date(raw: str, locale: str | None) -> date:
    text = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)
    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if not match:
        raise ValueError("Date format is not supported")
    first, second, year = map(int, match.groups())
    if first > 12 or locale in {"en-GB", "th-TH", "de-DE", "fr-FR"}:
        return date(year, second, first)
    if second > 12 or locale == "en-US":
        return date(year, first, second)
    raise ValueError("Ambiguous day/month order")


def normalize_reference(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).upper()
    text = re.sub(r"\d+", lambda match: match[0].lstrip("0") or "0", text)
    return re.sub(r"[\s\-/_\.]", "", text)


def thai_tax_id_valid(value: str) -> bool:
    if not re.fullmatch(r"\d{13}", value):
        return False
    return int(value[-1]) == (11 - sum(int(value[i]) * (13 - i) for i in range(12)) % 11) % 10


def normalize_country(raw: str) -> str:
    code = raw.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", code) or pycountry.countries.get(alpha_2=code) is None:
        raise ValueError("Country requires a recognized source territory code")
    return code
