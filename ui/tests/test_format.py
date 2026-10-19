"""Display helpers: THB and rate formatting, state colours, hashes, mandate field sources."""

from decimal import Decimal

import format as fmt


def test_thb_uses_thousands_separators_and_two_decimals():
    assert fmt.thb("524300.00") == "THB 524,300.00"
    assert fmt.thb(Decimal("749000")) == "THB 749,000.00"
    assert fmt.thb("25000", "USD") == "USD 25,000.00"
    assert fmt.thb(None) == "-"


def test_rate_pair_shows_the_30_day_fee_and_the_response_apr():
    assert fmt.rate_pair("0.009", "0.1095") == "0.90% / 30 days (10.95% APR)"
    assert fmt.rate_pair("0.012", "0.146") == "1.20% / 30 days (14.60% APR)"
    assert fmt.rate_pair("0.009", None) == "0.90% / 30 days"
    assert fmt.pct("0.70", 0) == "70%"


def test_state_colours_are_green_amber_red_and_unknown_is_never_green():
    assert fmt.state_colour("approve") == fmt.state_colour("executed") == fmt.GREEN
    assert fmt.state_colour("REVIEW") == fmt.state_colour("pending_approval") == fmt.AMBER
    assert fmt.state_colour("reject") == fmt.state_colour("blocked") == fmt.state_colour("failed") == fmt.RED
    assert fmt.state_colour("something else") == fmt.state_colour(None) == fmt.GREY


def test_short_hash_keeps_prefix_and_tail():
    value = "mock:0x" + "ab" * 32
    assert fmt.short_hash(value) == "mock:0xabababa…abab"
    assert fmt.short_hash("0x1234") == "0x1234"
    assert fmt.short_hash(None) == "-"


def test_field_source_and_reason_code():
    envelope = {"fields_from_text": ["max_apr"], "fields_from_llm": ["daily_cap"], "fields_from_defaults": []}
    assert fmt.field_source(envelope, "max_apr") == "text"
    assert fmt.field_source(envelope, "daily_cap") == "llm"
    assert fmt.field_source(envelope, "expires_at") == "default"
    assert fmt.reason_code("KO.DUPLICATE: already financed") == ("KO.DUPLICATE", "already financed")


def test_gauge_positions_pd_against_the_cap():
    assert fmt.gauge(0.0027, 0.05) == (0.027, 0.5)
    assert fmt.gauge(0.5, 0.05) == (1.0, 0.5)


def test_tone_gives_each_state_a_pale_tint_and_dark_ink_and_unknown_is_grey():
    assert fmt.tone(fmt.GREEN) == "background:#e6f4ec;color:#0f6b35;border-color:#1a7f37"
    assert "color:#a61b1b" in fmt.tone(fmt.RED)
    assert fmt.tone("#123456").startswith("background:#eef2f6;color:#3b4a5c")
