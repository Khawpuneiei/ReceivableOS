"""Demo scenarios 1-8 (brief section 11) against fixtures/requests and fixtures/expected.

Each request is a full /policy/decide body (shared demo invoice, section 5.3 profiles, the THB demo mandate,
as_of_date 2026-10-12). Each expected file lists the decision, the terms and the reason codes that must and
must not appear. risk_score is checked against a bound, not an exact value, so the trained model can replace
the placeholder PD without touching these files.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from factories import MANDATE, edited_rules, happy_body
from fastapi.testclient import TestClient

from app.decision import decide
from app.main import app
from app.schemas import PolicyRequestExt
from shared.schemas import PolicyDecision

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REQUESTS = FIXTURES / "requests"
EXPECTED = FIXTURES / "expected"
SCENARIOS = sorted(p.stem for p in REQUESTS.glob("*.json"))

client = TestClient(app)


def _load(folder: Path, name: str) -> dict:
    return json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))


def _run(name: str) -> dict:
    """The decision for one scenario: over HTTP, unless the expected file switches the default mandate off."""
    body, expected = _load(REQUESTS, name), _load(EXPECTED, name)
    if expected.get("use_default_mandate", True):
        r = client.post("/policy/decide", json=body)
        assert r.status_code == 200, r.text
        return r.json()
    d = decide(PolicyRequestExt.model_validate(body), use_default_mandate=False)
    return json.loads(d.model_dump_json())


def _codes(resp: dict) -> set[str]:
    return {reason.split(":", 1)[0] for reason in resp["reasons"]}


def test_every_scenario_has_an_expected_file():
    assert SCENARIOS == sorted(p.stem for p in EXPECTED.glob("*.json"))
    assert len(SCENARIOS) == 9  # 1-8 plus 8b


def test_happy_fixture_matches_the_test_factory():
    assert _load(REQUESTS, "01_happy") == happy_body()
    assert json.loads((FIXTURES / "mandates" / "demo_thb.json").read_text(encoding="utf-8")) == MANDATE


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_decision_terms_and_codes(name):
    expected, resp = _load(EXPECTED, name), _run(name)
    PolicyDecision.model_validate(resp)
    assert resp["decision"] == expected["decision"]
    for field in ("advance_rate", "limit", "fee_rate", "apr"):
        if field in expected:
            assert Decimal(resp[field]) == Decimal(expected[field]), field
    bounds = expected.get("risk_score", {})
    assert bounds.get("min", 0.0) <= resp["risk_score"] <= bounds.get("max", 1.0)
    assert resp["risk_score"] == resp["pd"]
    codes = _codes(resp)
    assert set(expected["must_contain"]) <= codes
    assert not set(expected.get("must_not_contain", [])) & codes
    effects = {d["code"]: d["effect"] for d in resp["reason_details"]}
    for code, effect in expected.get("effects", {}).items():
        assert effect in effects[code], code


@pytest.mark.parametrize("name", SCENARIOS)
def test_invariants(name):
    body, resp = _load(REQUESTS, name), _run(name)
    codes = _codes(resp)
    blocking = {c for c in codes if c.startswith(("HARD.", "KO.", "REVIEW."))}
    rate, limit, amount = (
        Decimal(resp["advance_rate"]),
        Decimal(resp["limit"]),
        Decimal(body["invoice"]["amount"]),
    )
    if resp["decision"] == "reject":
        assert (rate, limit, Decimal(resp["fee_rate"])) == (0, 0, 0)
        assert any(c.startswith(("HARD.", "KO.")) for c in codes)
    elif resp["decision"] == "review":
        assert any(c.startswith(("HARD.", "REVIEW.")) for c in codes)
    else:
        assert not blocking
    assert abs(rate * amount - limit) <= Decimal("0.01")
    mandate = body.get("mandate")
    if mandate:
        assert rate <= Decimal(mandate["max_ltv"])
        assert limit <= Decimal(mandate["max_amount_per_tx"])


@pytest.mark.parametrize("name", SCENARIOS)
def test_same_request_gives_the_same_hash(name):
    first, again = _run(name), _run(name)
    assert first["decision_hash"] == again["decision_hash"]
    assert first["decision_id"] == again["decision_id"]


def test_scenario_8b_over_http_gets_the_default_mandate():
    """Without a mandate in the request, the service applies its default mandate, so the cap binds again."""
    resp = client.post("/policy/decide", json=_load(REQUESTS, "08b_repeat_seller_no_mandate")).json()
    assert (resp["decision"], resp["advance_rate"]) == ("approve", "0.70")
    assert {"MANDATE.DEFAULT", "TERMS.HAIRCUT_DILUTION", "TERMS.MANDATE_CAP"} <= _codes(resp)


def test_scenario_1_with_no_mandate_gets_0_80():
    body = _load(REQUESTS, "01_happy")
    del body["mandate"]
    d = decide(PolicyRequestExt.model_validate(body), use_default_mandate=False)
    assert (d.decision.value, d.advance_rate, d.limit) == ("approve", Decimal("0.80"), Decimal("599200.00"))


def test_one_yaml_number_flips_scenario_1_to_review(tmp_path):
    """No threshold lives in Python: lowering the PD review gate in a YAML copy turns approve into review."""

    def lower_review_gate(raw: dict) -> None:
        assert raw["pd_gates"][1]["id"] == "REVIEW.PD_ABOVE_CAP"
        raw["pd_gates"][1]["param"]["review_above"] = 0.001

    rules = edited_rules(tmp_path, lower_review_gate)
    body = PolicyRequestExt.model_validate(_load(REQUESTS, "01_happy"))
    assert decide(body).decision.value == "approve"
    flipped = decide(body, rules=rules)
    assert flipped.decision.value == "review"
    assert "REVIEW.PD_ABOVE_CAP:hit" in flipped.rule_trace
