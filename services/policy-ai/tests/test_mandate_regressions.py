"""Regressions from the #31 review: a compiled mandate must never be looser than the sentence.

1. A cap with a unit suffix ("2m per day") was dropped and the 3m platform default applied.
2. A floor ("advance at least 80%") was read as a cap of 80%.
The parser now reads amounts before or after the unit phrase (k / m / mn / million / thousand / baht / บาท),
refuses minimum wording with AMBIGUOUS_VALUE, and refuses any amount next to "per day" / "per invoice" it
couldn't read with UNPARSED_CAP, so no stated limit can silently fall back to a looser default.
"""

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from wallet_mandate import WalletMandate

from app.mandate import MandateRejected, compile_mandate

NOW = datetime(2026, 10, 10, 0, 0, tzinfo=timezone(timedelta(hours=7)))


def _mandate(text: str) -> dict:
    return compile_mandate(text, now=NOW)["mandate"]


def _codes(text: str) -> set[tuple[str, str]]:
    with pytest.raises(MandateRejected) as exc:
        compile_mandate(text, now=NOW)
    return {(v.field, v.code) for v in exc.value.violations}


# --- 1. caps with unit suffixes are read, never replaced by the default ---


def test_review_sentence_2m_per_day_sets_the_daily_cap():
    assert _mandate("2m per day")["daily_cap"] == "2000000.00"
    m = _mandate("Never advance more than 70% and 2m per day")
    assert (m["max_ltv"], m["daily_cap"]) == ("0.70", "2000000.00")


@pytest.mark.parametrize(
    ("text", "field", "value"),
    [
        ("up to THB 2m per day", "daily_cap", "2000000.00"),
        ("THB 2,000,000 a day", "daily_cap", "2000000.00"),
        ("2 million baht daily", "daily_cap", "2000000.00"),
        ("2mn/day", "daily_cap", "2000000.00"),
        ("daily limit 1.5m", "daily_cap", "1500000.00"),
        ("daily 1.5m", "daily_cap", "1500000.00"),
        ("daily THB 2,000,000", "daily_cap", "2000000.00"),
        ("per day no more than 2500k", "daily_cap", "2500000.00"),
        ("2000000 บาท ต่อวัน", "daily_cap", "2000000.00"),
        ("วันละ 2,000,000 บาท", "daily_cap", "2000000.00"),
        ("1m per invoice", "max_amount_per_tx", "1000000.00"),
        ("max 500k per transaction", "max_amount_per_tx", "500000.00"),
        ("up to 500 thousand baht per transaction", "max_amount_per_tx", "500000.00"),
        ("per transaction up to 1.2m", "max_amount_per_tx", "1200000.00"),
        ("transaction limit THB 800,000", "max_amount_per_tx", "800000.00"),
        ("1,000,000 บาท ต่อรายการ", "max_amount_per_tx", "1000000.00"),
    ],
)
def test_unit_suffixes_next_to_per_day_and_per_transaction(text, field, value):
    assert _mandate(text)[field] == value


def test_both_caps_in_one_sentence_stay_in_their_own_clause():
    m = _mandate("max 1m per invoice, 2 million baht daily")
    assert (m["max_amount_per_tx"], m["daily_cap"]) == ("1000000.00", "2000000.00")
    m = _mandate("THB 2,000,000 a day and 1.2m per transaction")
    assert (m["max_amount_per_tx"], m["daily_cap"]) == ("1200000.00", "2000000.00")


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("THB 2m per business day", "daily_cap"),
        ("2m every working day", "daily_cap"),
        ("1m for any single invoice", "max_amount_per_tx"),
    ],
)
def test_an_amount_next_to_a_unit_phrase_the_parser_cant_read_is_unparsed_cap(text, field):
    assert (field, "UNPARSED_CAP") in _codes(text)


def test_any_other_unread_number_is_refused_rather_than_ignored():
    assert ("text", "UNRECOGNISED_NUMBER") in _codes("Invoices due within 60 days, advance 70%")
    # an amount next to "invoice" that isn't a recognised cap phrase is refused, not guessed
    assert ("max_amount_per_tx", "UNPARSED_CAP") in _codes("Finance my THB 749,000 invoice")


def test_a_percentage_after_daily_is_never_read_as_an_amount():
    assert _mandate("advance daily 70%")["max_ltv"] == "0.70"
    assert ("text", "UNRECOGNISED_NUMBER") in _codes("daily limit 70%")


@pytest.mark.parametrize(
    ("text", "days"),
    [("valid 7 days", 7), ("valid for 7 days", 7), ("good for 14 days", 14), ("expires in 7 days", 7)],
)
def test_stated_validity_in_days_sets_expires_at(text, days):
    envelope = compile_mandate(text, now=NOW)
    assert datetime.fromisoformat(envelope["mandate"]["expires_at"]) == NOW + timedelta(days=days)
    assert "expires_at" in envelope["fields_from_text"]


def test_validity_beyond_the_platform_maximum_is_refused():
    assert ("expires_at", "EXPIRY_INVALID") in _codes("valid 400 days")


# --- 2. floors are never caps ---


def test_review_sentence_advance_at_least_80_is_422():
    assert _codes("Advance at least 80%") == {("max_ltv", "AMBIGUOUS_VALUE")}


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("no less than 60% advance", "max_ltv"),
        ("advance not less than 60%", "max_ltv"),
        ("minimum advance 75%", "max_ltv"),
        ("advance 80% or more", "max_ltv"),
        ("advance over 80%", "max_ltv"),
        ("minimum APR 10%", "max_apr"),
        ("at least 8% APR", "max_apr"),
        ("buyer risk above 5%", "max_predicted_default"),
        ("at least 1m per day", "daily_cap"),
        ("never less than 1m per day", "daily_cap"),
        ("minimum 500k per invoice", "max_amount_per_tx"),
    ],
)
def test_minimum_wording_is_ambiguous_value(text, field):
    assert (field, "AMBIGUOUS_VALUE") in _codes(text)


@pytest.mark.parametrize(
    ("text", "field", "value"),
    [
        ("advance up to 75%", "max_ltv", "0.75"),
        ("advance no more than 65%", "max_ltv", "0.65"),
        ("never advance more than 70%", "max_ltv", "0.70"),
        ("advance at most 60%", "max_ltv", "0.60"),
        ("APR below 10%", "max_apr", "0.10"),
        ("never pay more than 12% APR", "max_apr", "0.12"),
        ("stop if buyer risk is above 5%", "max_predicted_default", "0.05"),
        ("max pd of 4%", "max_predicted_default", "0.04"),
    ],
)
def test_maximum_wording_is_a_cap(text, field, value):
    assert _mandate(text)[field] == value


# --- the general property: never looser than what the sentence states ---


def test_never_looser_than_the_sentence_property():
    """Random caps in random phrasings: the compiled cap equals the stated one, or the sentence is a 422."""
    rng = random.Random(11)
    daily = [
        "{a}m per day",
        "up to THB {a}m a day",
        "daily cap {a}m",
        "{a} million baht daily",
        "{a}m/day",
        "daily {a}m",
    ]
    per_tx = ["{b}k per invoice", "max {b}k per transaction", "per transaction up to {b}k"]
    floors = ["at least {a}m per day", "minimum {b}k per invoice", "no less than {p}% advance"]
    compiled = 0
    for _ in range(200):
        a, b, p = rng.choice([1, 2, 2.5, 3]), rng.choice([100, 500, 900, 1500]), rng.choice([50, 60, 70])
        parts = [rng.choice(daily), rng.choice(per_tx)] + ([rng.choice(floors)] if rng.random() < 0.3 else [])
        rng.shuffle(parts)
        text = ", ".join(parts).format(a=a, b=b, p=p)
        try:
            m = _mandate(text)
        except MandateRejected:
            continue
        compiled += 1
        assert Decimal(m["daily_cap"]) == Decimal(str(a)) * 1_000_000, text
        assert Decimal(m["max_amount_per_tx"]) == Decimal(b) * 1_000, text
        WalletMandate.model_validate(m)
    assert compiled > 50
