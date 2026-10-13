import random
from decimal import Decimal

import pymupdf
import pytest
from datagen.amount_words import english_words, invoice

from app.amount_words import amount_words_reason, parse_thai_number, thai_baht_text, written_amounts
from app.extract import extract_document
from app.worker import parse


@pytest.mark.parametrize(
    ("words", "value"),
    [
        ("เจ็ดแสนสี่หมื่นเก้าพัน", 749_000),
        ("สิบเอ็ด", 11),
        ("ยี่สิบเอ็ด", 21),
        ("หนึ่งร้อยเอ็ด", 101),
        ("หนึ่งล้านเอ็ด", 1_000_001),
        ("หนึ่งร้อยล้าน", 100_000_000),
        ("ล้าน", None),
        ("สองสาม", None),
        ("บริษัท", None),
    ],
)
def test_thai_number_words(words, value):
    assert parse_thai_number(words) == value


def test_thai_baht_text_round_trips():
    rng = random.Random(7)
    for _ in range(2000):
        amount = Decimal(rng.randint(0, 10**10)) + Decimal(rng.randint(0, 99)) / 100
        assert written_amounts(f"({thai_baht_text(amount)})") == [amount]
    assert thai_baht_text(Decimal("749000")) == "เจ็ดแสนสี่หมื่นเก้าพันบาทถ้วน"
    assert thai_baht_text(Decimal("1000001.21")) == "หนึ่งล้านเอ็ดบาทยี่สิบเอ็ดสตางค์"


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Amount in words: Seven Hundred Forty-Nine Thousand Baht Only", Decimal("749000")),
        (
            "SAY: THAI BAHT EIGHT HUNDRED TWENTY THREE THOUSAND NINE HUNDRED AND FIFTY SATANG ONLY",
            Decimal("823900.50"),
        ),
        ("Total in words: one hundred and five baht only", Decimal("105")),
        (f"Amount in words: {english_words(1_234_567)} Baht Only", Decimal("1234567")),
    ],
)
def test_english_amount_in_words(text, value):
    assert written_amounts(text) == [value]


@pytest.mark.parametrize(
    "text",
    [
        "Please pay only by bank transfer",
        "Amount in words: US Dollars Twelve Thousand and 50 cents only",  # mixed digits: skipped
        "Say: see attached schedule only",
        "ราคานี้รวมภาษีมูลค่าเพิ่มแล้ว",
    ],
)
def test_text_without_a_clean_amount_in_words_is_ignored(text):
    assert amount_words_reason([text], Decimal("749000.00")) is None


def test_mismatch_and_match():
    assert amount_words_reason(["(เจ็ดแสนสี่หมื่นเก้าพันบาทถ้วน)"], Decimal("749000.00")) is None
    assert amount_words_reason(["(เจ็ดแสนสี่หมื่นเก้าพันบาทถ้วน)"], Decimal("794000.00")) == "AMOUNT_WORDS_MISMATCH"
    assert amount_words_reason(["(เจ็ดแสนสี่หมื่นเก้าพันบาทถ้วน)"], None) is None


def _reasons(content: bytes) -> list[str]:
    return extract_document(parse(content), "invoice").document.review_reasons


def test_regenerated_digits_with_stale_words_need_review():
    # 55,000 trays -> 823,900.00 in digits; every arithmetic check agrees, but the words say 749,000.
    reasons = _reasons(invoice(55_000, Decimal("749000.00"), "WORDS-TEST-0001"))
    assert "AMOUNT_WORDS_MISMATCH" in reasons
    assert not any(reason.startswith(("TOTAL_MISMATCH", "LINE_")) for reason in reasons)


def test_honest_invoice_with_words_stays_clean():
    assert "AMOUNT_WORDS_MISMATCH" not in _reasons(invoice(50_000, None, "WORDS-TEST-0002"))


def test_thai_words_alone_are_enough():
    content = invoice(55_000, Decimal("749000.00"), "WORDS-TEST-0003", thai=True)
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        page = doc[0]
        english = page.search_for("Amount in words")[0]
        page.add_redact_annot(pymupdf.Rect(english.x0, english.y0, 330, english.y1))
        page.apply_redactions()
        content = doc.tobytes()
    assert "AMOUNT_WORDS_MISMATCH" in _reasons(content)
