import secrets
from datetime import date

import pytest
from datagen.thai_dates import FORMATS, thai_invoice

from app.config import Settings
from app.normalize import normalize_date
from app.pipeline import extract_invoice


@pytest.mark.parametrize(
    ("raw", "locale", "expected"),
    [
        ("01/10/2569", "th-TH", date(2026, 10, 1)),
        ("2569-10-01", None, date(2026, 10, 1)),
        ("1 ตุลาคม 2569", None, date(2026, 10, 1)),
        ("1 ต.ค. 2569", None, date(2026, 10, 1)),
        ("1 ต.ค.2569", None, date(2026, 10, 1)),
        ("1 ต.ค. พ.ศ. 2569", None, date(2026, 10, 1)),
        ("๑๕ พ.ย. ๒๕๖๙", None, date(2026, 11, 15)),
        ("31 ธันวาคม 2569", None, date(2026, 12, 31)),
        ("1 Oct 2026", None, date(2026, 10, 1)),
        ("October 1, 2026", None, date(2026, 10, 1)),
        ("Sept 30, 2026", None, date(2026, 9, 30)),
        ("1 Oct 2026 A.D.", None, date(2026, 10, 1)),
        ("2026-10-01", None, date(2026, 10, 1)),
    ],
)
def test_supported_date_notations(raw, locale, expected):
    assert normalize_date(raw, locale) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "1 ต.ค. 69",  # two-digit year: era and century unknown
        "2300-01-01",  # neither plausible CE nor BE
        "1 Foo 2026",
        "31 ก.พ. 2569",  # no 31 February
        "01/02/2026",  # day/month order needs locale evidence
        "2026 ค.ศ. 2569",
    ],
)
def test_unsupported_or_ambiguous_dates_stay_unresolved(raw):
    with pytest.raises(ValueError):
        normalize_date(raw, None)


def test_explicit_ce_marker_keeps_a_ce_year():
    with pytest.raises(ValueError):
        normalize_date("2569-10-01 A.D.", None)


@pytest.mark.parametrize("name", list(FORMATS))
def test_thai_invoice_dates_and_fingerprint_match_iso_whatever_the_notation(name, tmp_path):
    keys = ("a" * 64, "b" * 64)
    settings = Settings(*keys, tmp_path / f"{name}.sqlite", False, False, "", "", True, False)
    iso = Settings(*keys, tmp_path / "iso.sqlite", False, False, "", "", True, False)
    response = extract_invoice(thai_invoice(*FORMATS[name]), settings, None)
    reference = extract_invoice(thai_invoice(*FORMATS["iso_ce"]), iso, None)
    assert (response.issue_date, response.due_date) == (date(2026, 10, 1), date(2026, 11, 15))
    assert response.invoice_fingerprint == reference.invoice_fingerprint


def test_be_resubmission_of_a_ce_invoice_is_a_duplicate(tmp_path):
    settings = Settings(
        secrets.token_hex(32), secrets.token_hex(32), tmp_path / "s.sqlite", False, False, "", "", True, False
    )
    extract_invoice(thai_invoice(*FORMATS["iso_ce"]), settings, None)
    again = extract_invoice(thai_invoice(*FORMATS["thai_abbrev_be"]), settings, None)
    assert "duplicate_fingerprint" in again.fraud_flags
