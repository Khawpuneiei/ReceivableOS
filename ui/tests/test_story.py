"""The step strip and the plain-language verdict (ui/story.py), on the saved fixtures and edited copies."""

import copy
import json
from pathlib import Path

import story

HAPPY = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "happy.json").read_text("utf-8"))


def _states(view, paid=False):
    return [s["state"] for s in story.steps(view, paid)]


def test_a_funded_invoice_is_green_to_the_wallet_and_waits_for_the_buyer():
    assert _states(HAPPY) == ["done"] * 5 + ["waiting"]
    assert _states(HAPPY, paid=True) == ["done"] * 6
    state, headline, sentence = story.verdict(HAPPY)
    assert state == "done" and headline == "Funded inside the rules" and "Lender A" in sentence


def test_an_injected_invoice_is_held_for_a_person_in_plain_words():
    view = copy.deepcopy(HAPPY)
    view["ocr"]["injection_flags"] = ["VISIBLE_INSTRUCTION"]
    view["policy"] = {**view["policy"], "decision": "review", "reasons": ["HARD.INJECTION: 1 flag"]}
    view["timeline"], view["wallet"] = view["timeline"][:1], {"status": "review: wallet not called"}
    assert _states(view) == ["done", "review", "done", "review", "skipped", "skipped"]
    state, _, sentence = story.verdict(view)
    assert state == "review" and "tries to give the AI instructions" in sentence


def test_a_rejected_invoice_lists_every_reason_once():
    view = copy.deepcopy(HAPPY)
    reasons = [
        "HARD.FRAUD_SCORE: 0.4",
        "REVIEW.LINE_ITEMS_MISMATCH: x",
        "MODEL.PD: 0.5%",
        "HARD.FRAUD_SCORE: again",
    ]
    view["policy"] = {**view["policy"], "decision": "reject", "reasons": reasons}
    view["timeline"], view["wallet"] = view["timeline"][:1], {"status": "reject: wallet not called"}
    state, headline, sentence = story.verdict(view)
    assert state == "stopped" and headline.startswith("Rejected")
    assert sentence == (
        "Rejected because the fraud checks scored the invoice too risky and the line items do not add up "
        "to the invoice total."
    )


def test_a_duplicate_stops_at_the_registry_and_skips_the_rest():
    view = copy.deepcopy(HAPPY)
    view["registry"]["duplicate"], view["policy"] = True, None
    view["timeline"] = [{"step": "TX-1", "status": "blocked", "block_reason": "DuplicateReceivable"}]
    view["wallet"] = {"status": "blocked: DuplicateReceivable"}
    assert _states(view) == ["done", "done", "stopped", "skipped", "skipped", "skipped"]
    assert "cannot be financed twice" in story.verdict(view)[2]


def test_unknown_codes_have_no_made_up_explanation():
    assert story.plain("SOMETHING.NEW") is None and story.plain(None) is None
    assert story.plain("AprAboveMandate") == "the lender's APR is above the SME's ceiling"


def test_findings_use_the_ocr_details_when_present_and_the_flags_otherwise():
    newer = {
        "fraud_flags": ["qr_payee_mismatch"],
        "fraud_details": [{"code": "qr_payee_mismatch", "weight": 0.4, "reason": "possible QR swap"}],
        "injection_flags": ["VISIBLE_INSTRUCTION"],
        "injection_details": [
            {"category": "payee_redirect", "technique": "homoglyph", "channel": "page_text"}
        ],
    }
    found = story.findings(newer)
    assert found[0] == {
        "kind": "fraud",
        "headline": "the payment QR pays someone other than the supplier",
        "detail": "possible QR swap",
        "weight": 0.4,
    }
    assert found[1]["headline"] == "hidden instructions for the AI: tries to redirect the payment"
    assert found[1]["detail"] == "look-alike-letter text in the page text"
    older = {
        "fraud_flags": ["math_inconsistent", "brand_new_code"],
        "injection_flags": ["VISIBLE_INSTRUCTION"],
    }
    assert [f["headline"] for f in story.findings(older)] == [
        "the line items do not add up to the total",
        "brand new code",
        "instructions for the AI found in the document (VISIBLE_INSTRUCTION)",
    ]
    assert story.findings({}) == []


def test_the_verdict_names_what_the_document_checks_found():
    view = copy.deepcopy(HAPPY)
    view["ocr"]["fraud_flags"] = ["pdf_appended_text_layer"]
    view["policy"] = {**view["policy"], "decision": "review", "reasons": ["REVIEW.FRAUD_FLAGS: 1 flag"]}
    view["timeline"], view["wallet"] = view["timeline"][:1], {"status": "review: wallet not called"}
    assert story.verdict(view)[2].endswith(
        "The document checks found: text was added to the PDF after it was made."
    )


def test_validation_flags_and_newer_injection_categories_read_in_words():
    inv = {
        "validation_flags": ["AMOUNT_WORDS_MISMATCH"],
        "injection_details": [{"category": "exfiltration", "technique": "plain", "channel": "page_text"}],
    }
    heads = [f["headline"] for f in story.findings(inv)]
    assert heads == [
        "the total written in words does not match the digits",
        "hidden instructions for the AI: tries to make the AI leak data",
    ]
