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


THAI_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
    "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
}  # fmt: skip
ENGLISH_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",),
            ("june", "jun"), ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"),
            ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}  # fmt: skip
BUDDHIST_ERA = re.compile(r"พ\.\s?ศ\.|\bB\.?\s?E\.?(?=\s|$)", re.IGNORECASE)
COMMON_ERA = re.compile(r"ค\.\s?ศ\.|\bA\.?\s?D\.?(?=\s|$)|\bC\.?\s?E\.?(?=\s|$)", re.IGNORECASE)
BE_OFFSET = 543


def _year(value: int, era: str | None) -> int:
    """Resolve a four-digit year; Buddhist Era years (Thai invoices) are converted to CE."""
    if era == "BE" or (era is None and 2400 <= value <= 2700):
        if not 2400 <= value <= 2700:
            raise ValueError("Buddhist Era year is out of range")
        return value - BE_OFFSET
    if value > 2200:
        raise ValueError("Year is neither a plausible CE nor a Buddhist Era year")
    return value


def normalize_date(raw: str, locale: str | None) -> date:
    text = unicodedata.normalize("NFKC", raw).strip()
    # Thai digits (๐-๙) and other decimal scripts become ASCII; separators stay as printed.
    text = "".join(str(unicodedata.decimal(char)) if char.isdecimal() else char for char in text)
    era = "BE" if BUDDHIST_ERA.search(text) else "CE" if COMMON_ERA.search(text) else None
    text = re.sub(r"\s+", " ", COMMON_ERA.sub(" ", BUDDHIST_ERA.sub(" ", text))).strip()
    if match := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text):
        year, month, day = map(int, match.groups())
        return date(_year(year, era), month, day)
    if match := re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text):
        first, second, year = map(int, match.groups())
        year = _year(year, era)
        if first > 12 or locale in {"en-GB", "th-TH", "de-DE", "fr-FR"}:
            return date(year, second, first)
        if second > 12 or locale == "en-US":
            return date(year, first, second)
        raise ValueError("Ambiguous day/month order")
    # Named months carry no day/month ambiguity: "1 ตุลาคม 2569", "1 ต.ค. 2569", "1 Oct 2026", "Oct 1, 2026".
    if match := re.fullmatch(r"(\d{1,2}) ?(\D+?) ?(\d{4})", text):
        day, name, year = match.groups()
        name = name.strip().replace(" ", "")
        month = THAI_MONTHS.get(name) or ENGLISH_MONTHS.get(name.rstrip(".,").casefold())
        if month:
            return date(_year(int(year), era), month, int(day))
    if match := re.fullmatch(r"([A-Za-z]+)\.? (\d{1,2}),? (\d{4})", text):
        name, day, year = match.groups()
        if month := ENGLISH_MONTHS.get(name.casefold()):
            return date(_year(int(year), era), month, int(day))
    raise ValueError("Date format is not supported")


def normalize_reference(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).upper()

    def numeric_run(match):
        digits = "".join(str(unicodedata.decimal(char)) for char in match[0])
        return digits.lstrip("0") or "0"

    text = re.sub(r"\d+", numeric_run, text)
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
