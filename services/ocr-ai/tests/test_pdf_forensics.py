import secrets
from pathlib import Path

import pytest
from datagen.security_corpus import overlay
from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf
from datagen.tamper_corpus import ATTACKS, BENIGN, benign, forge

from app.config import FRAUD_WEIGHTS, Settings
from app.fraud import finding, score
from app.pipeline import extract_invoice
from app.worker import parse

REPO = Path(__file__).resolve().parents[3]
PDF_CODES = ("pdf_text_covered", "pdf_appended_text_layer", "pdf_font_anomaly", "pdf_incremental_update")


def settings(tmp_path) -> Settings:
    return Settings(
        secrets.token_hex(32), secrets.token_hex(32), tmp_path / "s.sqlite", False, False, "", "", True, False
    )


def signals(content: bytes) -> set[str]:
    parsed = parse(content)
    found = {flag for span in parsed.spans for flag in span.forensic}
    return found | ({"incremental"} if parsed.incremental_updates else set())


def test_cover_and_retype_hides_the_old_amount_and_reads_the_visible_one():
    parsed = parse(forge("cover_retype", "TAMPER-T-0001"))
    covered = [span.text for span in parsed.spans if "covered" in span.forensic]
    assert "Total: 749,000.00" in covered
    assert all(span.hidden for span in parsed.spans if "covered" in span.forensic)
    visible = [span.text for span in parsed.spans if not span.hidden]
    assert "Total: 856,000.00" in visible


@pytest.mark.parametrize("kind", ATTACKS)
def test_forged_invoices_carry_an_edit_signal_and_are_not_auto_approved(kind, tmp_path):
    response = extract_invoice(forge(kind, "TAMPER-T-0002"), settings(tmp_path), None)
    assert set(response.fraud_flags) & set(PDF_CODES)
    assert response.review_required
    assert 0 < response.fraud_score < 0.30  # review, not an automatic reject


def test_incremental_page_edit_is_flagged():
    assert "incremental" in signals(forge("redact_retype_incremental", "TAMPER-T-0003"))


def test_other_font_on_amount_is_flagged():
    assert "font_anomaly" in signals(forge("redact_retype_other_font", "TAMPER-T-0004"))


@pytest.mark.parametrize("kind", BENIGN)
def test_benign_edits_carry_no_signal(kind):
    assert signals(benign(kind, "TAMPER-B-0001")) == set()


def test_dark_header_drawn_before_text_is_not_cover():
    clean = build_pdf({**SHOWCASE_PROFILES[0], "invoice_no": "TAMPER-B-0002"})
    assert signals(overlay(clean, "dark_header", benign=True)) == set()


@pytest.mark.parametrize("name", ["01_happy.pdf", "02_injected.pdf", "03_inflated.pdf", "04_duplicate.pdf"])
def test_checked_in_demo_files_are_untouched(name):
    assert signals((REPO / "data/invoices/demo" / name).read_bytes()) == set()


def test_tampered_demo_file_shows_the_edit():
    assert "appended" in signals((REPO / "data/invoices/demo/05_tampered.pdf").read_bytes())


def test_all_edit_signals_together_stay_below_reject_threshold():
    assert score([finding(code, "x") for code in PDF_CODES]) < 0.30
    assert all(code in FRAUD_WEIGHTS for code in PDF_CODES)
