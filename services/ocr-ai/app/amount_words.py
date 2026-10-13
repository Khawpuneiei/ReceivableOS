"""Cross-check the printed amount in words against the numeric total.

Thai invoices print the total in words (``บาทถ้วน``, the BAHTTEXT form) and English ones often
carry "Amount in words: ... only". Someone who edits or regenerates the digits often leaves
the words alone, so a disagreement is a cheap, deterministic tamper signal. The words are
document text: this module only parses number words and never treats them as instructions.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

THAI_DIGITS = {
    "ศูนย์": 0, "หนึ่ง": 1, "เอ็ด": 1, "สอง": 2, "ยี่": 2, "สาม": 3, "สี่": 4, "ห้า": 5, "หก": 6, "เจ็ด": 7,
    "แปด": 8, "เก้า": 9,
}  # fmt: skip
THAI_UNITS = {"สิบ": 10, "ร้อย": 100, "พัน": 1_000, "หมื่น": 10_000, "แสน": 100_000}
THAI_TOKEN = "|".join(sorted([*THAI_DIGITS, *THAI_UNITS, "ล้าน"], key=len, reverse=True))
THAI_WORDS = re.compile(rf"((?:{THAI_TOKEN}|\s)+)บาท\s*(?:ถ้วน|ตรง|((?:{THAI_TOKEN}|\s)+)สตางค์)")

ENGLISH_NUMBERS = {
    word: value
    for value, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen".split()
    )
} | {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
     "eighty": 80, "ninety": 90}  # fmt: skip
ENGLISH_SCALES = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
ENGLISH_WORDS = re.compile(
    r"\b(?:amount|total|sum)\s+in\s+words\b\s*[:\-]?\s*(.{3,200}?)\bonly\b|\bsay\s*[:\-]\s*(.{3,200}?)\bonly\b",
    re.IGNORECASE,
)
MINOR = re.compile(r"\s+(?:satang|stang|cents?)\b", re.IGNORECASE)
NOISE = re.compile(r"\b(?:thai|baht|bahts|thb|us|usd|dollars?|euros?|eur|and|only)\b", re.IGNORECASE)


def _thai_below_million(text: str) -> int | None:
    total, digit, position = 0, None, 0
    for token in re.findall(THAI_TOKEN, text):
        if token in THAI_DIGITS:
            if digit is not None:
                return None  # two digits in a row are not a number
            digit = THAI_DIGITS[token]
        else:
            total += (1 if digit is None else digit) * THAI_UNITS[token]
            digit = None
        position += len(token)
    if position != len(text):
        return None
    return total + (digit or 0)


def parse_thai_number(text: str) -> int | None:
    """``หนึ่งล้านสองแสนเอ็ด`` -> 1200001; None when the text is not only Thai number words."""
    text = re.sub(r"\s+", "", unicodedata.normalize("NFC", text))
    if not text:
        return None
    groups = text.split("ล้าน")
    if not groups[0]:
        return None  # "ล้าน" needs a multiplier in front of it
    value = 0
    for group in groups:
        part = _thai_below_million(group) if group else 0
        if part is None:
            return None
        value = value * 1_000_000 + part
    return value


def thai_baht_text(amount: Decimal) -> str:
    """Render ``amount`` the way Thai invoices print it (Excel BAHTTEXT form)."""

    def words(value: int) -> str:
        if value == 0:
            return ""
        millions, rest = divmod(value, 1_000_000)
        out = words(millions) + "ล้าน" if millions else ""
        digits = str(rest).zfill(6)
        names = ["", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
        units = ["แสน", "หมื่น", "พัน", "ร้อย", "สิบ", ""]
        for index, char in enumerate(digits):
            digit = int(char)
            if not digit:
                continue
            if index == 4:
                out += ("ยี่" if digit == 2 else "" if digit == 1 else names[digit]) + "สิบ"
            elif index == 5:
                out += "เอ็ด" if digit == 1 and (value > 9) else names[digit]
            else:
                out += names[digit] + units[index]
        return out

    baht, satang = divmod(int((amount * 100).to_integral_value()), 100)
    head = (words(baht) or "ศูนย์") + "บาท"
    return head + (words(satang) + "สตางค์" if satang else "ถ้วน")


def parse_english_number(text: str) -> int | None:
    """``seven hundred forty-nine thousand`` -> 749000; None when any word is not a number word."""
    total, current, seen = 0, 0, False
    for word in re.split(r"[\s,-]+", text.lower().strip()):
        if not word:
            continue
        if word in ENGLISH_NUMBERS:
            current += ENGLISH_NUMBERS[word]
        elif word == "hundred":
            current = (current or 1) * 100
        elif word in ENGLISH_SCALES:
            total += (current or 1) * ENGLISH_SCALES[word]
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


def written_amounts(text: str) -> list[Decimal]:
    """Every amount written out in words in ``text``, in Thai BAHTTEXT or English "... only" form."""
    found = []
    text = unicodedata.normalize("NFC", text)
    for match in THAI_WORDS.finditer(text):
        baht = parse_thai_number(match.group(1))
        satang = parse_thai_number(match.group(2)) if match.group(2) else 0
        if baht is not None and satang is not None and satang < 100:
            found.append(Decimal(baht) + Decimal(satang) / 100)
    for match in ENGLISH_WORDS.finditer(text):
        phrase = match.group(1) or match.group(2)
        minor = MINOR.search(phrase)
        cents = 0
        if minor:
            # "... nine hundred and fifty satang": the minor unit is whatever follows the last "and".
            major_part, _, minor_part = phrase[: minor.start()].lower().rpartition(" and ")
            cents = parse_english_number(NOISE.sub(" ", minor_part)) if major_part else None
            phrase = major_part
        major = parse_english_number(NOISE.sub(" ", phrase))
        if major is not None and cents is not None and cents < 100:
            found.append(Decimal(major) + Decimal(cents) / 100)
    return found


def amount_words_reason(texts: list[str], amount: Decimal | None) -> str | None:
    """``AMOUNT_WORDS_MISMATCH`` when any amount in words disagrees with the extracted total."""
    if amount is None:
        return None
    written = [value for text in texts for value in written_amounts(text)]
    if any(value != amount for value in written):
        return "AMOUNT_WORDS_MISMATCH"
    return None
