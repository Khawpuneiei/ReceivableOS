"""Placeholder PD, PD gates and review triggers: one test per rule, at its boundary."""

from decimal import Decimal

import pytest
from factories import ctx_for, edited_rules, happy_body, rule_entry

from app import model
from app.engine import merge_outcome, run_pre_terms
from shared.schemas import Decision


def _run(body: dict, rules=None) -> dict:
    _, results = run_pre_terms(ctx_for(body, rules))
    return {r.id: r for r in results}


def _hit_ids(body: dict, rules=None) -> set[str]:
    return {rule_id for rule_id, r in _run(body, rules).items() if r.status == "hit"}


def _fixed_pd(monkeypatch, pd: float) -> None:
    monkeypatch.setattr(model, "predict_pd", lambda buyer, tenor_days: pd)


# --- Placeholder PD ---


def test_placeholder_pd_reproduces_the_demo_numbers():
    happy = ctx_for(happy_body())
    pd = model.predict_pd(happy.buyer, happy.tenor_days)
    assert pd == pytest.approx(0.0029, abs=0.00005)
    assert pd < 0.00347  # keeps the demo fee at 0.009 per 30 days

    body = happy_body()
    body["buyer_profile"]["buyer_confirmed"] = False  # variant V3
    v3 = ctx_for(body)
    assert 0.0036 < model.predict_pd(v3.buyer, v3.tenor_days) <= 0.0058  # fee 0.012
    assert model.MODEL_VERSION == "scorecard-fallback"


def test_placeholder_pd_imputes_missing_inputs():
    body = happy_body()
    body["buyer_profile"] = {}
    ctx = ctx_for(body)
    pd = model.predict_pd(ctx.buyer, ctx.tenor_days)
    assert 0.0029 < pd < 0.15  # scored as an unconfirmed tier C buyer, never an error


def test_happy_path_has_no_hits_and_carries_pd():
    ctx, results = run_pre_terms(ctx_for(happy_body()))
    assert ctx.pd == Decimal(str(model.predict_pd(ctx.buyer, ctx.tenor_days)))
    assert [r.trace for r in results if r.status != "pass"] == ["REVIEW.LARGE_TICKET:skip(disabled)"]
    assert merge_outcome(results) == Decision.approve


# --- PD gates ---


def test_pd_above_platform_maximum_rejects(monkeypatch):
    _fixed_pd(monkeypatch, 0.1501)
    r = _run(happy_body())["KO.PD_TOO_HIGH"]
    assert (r.status, r.outcome) == ("hit", "reject")
    _fixed_pd(monkeypatch, 0.15)
    assert "KO.PD_TOO_HIGH" not in _hit_ids(happy_body())


def test_pd_above_review_cap_reviews(monkeypatch):
    _fixed_pd(monkeypatch, 0.06)
    results = _run(happy_body())
    assert (results["REVIEW.PD_ABOVE_CAP"].status, results["REVIEW.PD_ABOVE_CAP"].outcome) == (
        "hit",
        "review",
    )
    assert results["KO.PD_TOO_HIGH"].status == "pass"
    _fixed_pd(monkeypatch, 0.05)
    assert "REVIEW.PD_ABOVE_CAP" not in _hit_ids(happy_body())


def test_lower_mandate_pd_cap_wins():
    body = happy_body()
    body["mandate"]["max_predicted_default"] = "0.002"  # below the demo PD of about 0.0029
    assert "REVIEW.PD_ABOVE_CAP" in _hit_ids(body)


def test_looser_mandate_pd_cap_never_loosens(monkeypatch):
    _fixed_pd(monkeypatch, 0.06)
    body = happy_body()
    body["mandate"]["max_predicted_default"] = "0.10"
    assert "REVIEW.PD_ABOVE_CAP" in _hit_ids(body)  # min(review_above 0.05, 0.10)
    del body["mandate"]
    assert "REVIEW.PD_ABOVE_CAP" in _hit_ids(body)  # no mandate: platform default max_pd


# --- Review triggers ---


@pytest.mark.parametrize("confirmation", [{"buyer_confirmed": False}, {}])
def test_unconfirmed_or_unknown_confirmation_reviews(confirmation):
    body = happy_body()
    del body["buyer_profile"]["buyer_confirmed"]
    body["buyer_profile"].update(confirmation)
    r = _run(body)["REVIEW.UNCONFIRMED_BUYER"]
    assert (r.status, r.outcome) == ("hit", "review")


def test_buyer_acknowledged_counts_as_confirmed():
    body = happy_body()
    del body["buyer_profile"]["buyer_confirmed"]
    body["buyer_profile"]["buyer_acknowledged"] = True
    assert "REVIEW.UNCONFIRMED_BUYER" not in _hit_ids(body)


@pytest.mark.parametrize("flag", ["near_duplicate", "injection_attempt", "stub"])
def test_fraud_flags_not_handled_by_a_knockout_review(flag):
    body = happy_body()
    body["invoice"]["fraud_flags"] = [flag]
    r = _run(body)["REVIEW.FRAUD_FLAGS"]
    assert (r.status, r.outcome) == ("hit", "review")
    assert flag not in r.message  # only the count is reported


def test_knockout_flags_do_not_also_review():
    body = happy_body()
    body["invoice"]["fraud_flags"] = ["duplicate_fingerprint", "PO_MISMATCH"]
    hit_ids = _hit_ids(body)
    assert {"KO.DUPLICATE", "KO.PO_MISMATCH"} <= hit_ids
    assert "REVIEW.FRAUD_FLAGS" not in hit_ids


@pytest.mark.parametrize(
    ("totals", "amount", "hits"),
    [
        (["700000.00"], "749000.00", False),  # plus 7% VAT
        (["700000.00", "49000.00"], "749000.00", False),  # VAT as its own line, 0% on top
        (["748999.99"], "749000.00", False),  # within the 0.01 tolerance
        (["748999.98"], "749000.00", True),
        (["700000.00"], "749500.00", True),
    ],
)
def test_line_items_must_sum_to_the_amount(totals, amount, hits):
    body = happy_body()
    body["invoice"]["amount"] = amount
    body["invoice"]["line_items"] = [{"description": "x", "unit_price": t, "total": t} for t in totals]
    assert ("REVIEW.LINE_ITEMS_MISMATCH" in _hit_ids(body)) is hits


def test_no_line_items_skips_the_check():
    body = happy_body()
    body["invoice"]["line_items"] = []
    assert _run(body)["REVIEW.LINE_ITEMS_MISMATCH"].trace == "REVIEW.LINE_ITEMS_MISMATCH:skip(missing)"


def test_new_supplier_boundary():
    body = happy_body()
    body["supplier_profile"]["invoices_financed_count"] = 2
    assert "REVIEW.NEW_SUPPLIER" in _hit_ids(body)
    body["supplier_profile"]["invoices_financed_count"] = 3
    assert "REVIEW.NEW_SUPPLIER" not in _hit_ids(body)
    del body["supplier_profile"]["invoices_financed_count"]
    assert _run(body)["REVIEW.NEW_SUPPLIER"].trace == "REVIEW.NEW_SUPPLIER:skip(missing)"


def test_large_ticket_is_off_by_default():
    body = happy_body()
    body["invoice"]["amount"] = "2000000.00"
    assert _run(body)["REVIEW.LARGE_TICKET"].trace == "REVIEW.LARGE_TICKET:skip(disabled)"


@pytest.fixture
def large_ticket_on(tmp_path):
    return edited_rules(
        tmp_path,
        lambda raw: rule_entry(raw, "review_triggers", "REVIEW.LARGE_TICKET")["param"].update(enabled=True),
    )


def test_large_ticket_when_switched_on(large_ticket_on):
    body = happy_body()
    body["invoice"]["line_items"] = []
    body["invoice"]["amount"] = "837500.00"
    assert "REVIEW.LARGE_TICKET" in _hit_ids(body, large_ticket_on)  # inclusive
    body["invoice"]["amount"] = "837499.99"
    assert "REVIEW.LARGE_TICKET" not in _hit_ids(body, large_ticket_on)
    body["mandate"]["human_review_above"] = "500000.00"  # the mandate's value wins
    assert "REVIEW.LARGE_TICKET" in _hit_ids(body, large_ticket_on)


def test_large_ticket_without_mandate_uses_the_currency_default(large_ticket_on):
    body = happy_body()
    del body["mandate"]
    body["invoice"].update(currency="USD", amount="25000.00", line_items=[])
    assert "REVIEW.LARGE_TICKET" in _hit_ids(body, large_ticket_on)
    body["invoice"]["amount"] = "24999.99"
    assert "REVIEW.LARGE_TICKET" not in _hit_ids(body, large_ticket_on)


def test_buyer_without_tier_or_rating_is_a_thin_profile():
    body = happy_body()
    del body["buyer_profile"]["internal_rating"]
    r = _run(body)["REVIEW.THIN_PROFILE"]
    assert (r.status, r.outcome) == ("hit", "review")
    assert "tier C" in r.message


def test_all_review_hits_are_collected():
    body = happy_body()
    body["buyer_profile"]["buyer_confirmed"] = False
    body["invoice"]["fraud_flags"] = ["near_duplicate"]
    _, results = run_pre_terms(ctx_for(body))
    assert {"REVIEW.UNCONFIRMED_BUYER", "REVIEW.FRAUD_FLAGS"} <= {r.id for r in results if r.status == "hit"}
    assert merge_outcome(results) == Decision.review
