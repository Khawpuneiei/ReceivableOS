import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import (
    ApproveIntent,
    GuardResult,
    Mandate,
    canonical_json,
    intent_hash,
    load_mandate,
)
from shared.schemas import GuardCheck, WalletRequest

SERVICE = Path(__file__).resolve().parents[1]
MANDATE_JSON = SERVICE / "config" / "mandate.demo.json"
FP = "0x" + "ab" * 32
DH = "0x" + "cd" * 32


def demo_mandate_dict() -> dict:
    return json.loads(MANDATE_JSON.read_text(encoding="utf-8"))


def test_demo_mandate_has_the_finance_values():
    m = load_mandate(MANDATE_JSON)
    assert m.max_ltv == Decimal("0.70")
    assert m.max_apr == Decimal("0.12")
    assert m.max_predicted_default == Decimal("0.05")
    assert m.human_review_above == Decimal("837500.00")
    assert m.mandate_hash is not None
    assert m.mandate_hash == m.compute_hash()


def test_mandate_hash_is_stable_and_changes_with_any_field():
    d = demo_mandate_dict()
    h1 = Mandate.model_validate(d).mandate_hash
    h2 = Mandate.model_validate(copy.deepcopy(d)).mandate_hash
    assert h1 == h2
    d["max_apr"] = "0.11"
    assert Mandate.model_validate(d).mandate_hash != h1


def test_policy_ai_aliases_map_to_canonical_fields():
    aliased = demo_mandate_dict()
    aliased["max_advance_rate"] = aliased.pop("max_ltv")
    aliased["max_pd"] = aliased.pop("max_predicted_default")
    aliased["human_review_above_thb"] = aliased.pop("human_review_above")
    aliased["allowed_settlement_asset"] = aliased.pop("settlement_asset")
    aliased["duplicate_invoice_policy"] = aliased.pop("duplicate_policy")
    assert Mandate.model_validate(aliased).compute_hash() == load_mandate(MANDATE_JSON).compute_hash()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_apr", "1.0"),  # above the 0.30 hard bound
        ("max_ltv", "0.95"),  # above the 0.90 hard bound
        ("max_predicted_default", "0.5"),
        ("max_apr", "0"),  # must be strictly positive
        ("max_amount_per_tx", "1500000.001"),  # more than 2 decimals (tTHB)
        ("daily_cap", "-1.00"),
        ("duplicate_policy", "ALLOW"),
        ("settlement_asset", "USDC"),
        ("valid_from", "2026-10-10T00:00:00"),  # naive datetime
    ],
)
def test_out_of_bounds_mandate_is_rejected(field, value):
    d = demo_mandate_dict()
    d[field] = value
    with pytest.raises(ValidationError):
        Mandate.model_validate(d)


def test_mandate_with_a_stale_hash_is_rejected():
    d = demo_mandate_dict()
    d["mandate_hash"] = Mandate.model_validate(d).compute_hash()
    d["max_apr"] = "0.20"  # loosened without re-hashing
    with pytest.raises(ValidationError):
        Mandate.model_validate(d)


def test_expiry_must_follow_start():
    d = demo_mandate_dict()
    d["expires_at"] = "2026-10-01T00:00:00+07:00"
    with pytest.raises(ValidationError):
        Mandate.model_validate(d)


def test_mandate_cannot_exceed_platform_ceilings():
    m = load_mandate(MANDATE_JSON)
    m.within_ceilings(Decimal("1500000.00"), Decimal("3000000.00"))  # equal is allowed
    with pytest.raises(ValueError):
        m.within_ceilings(Decimal("1000000.00"), Decimal("3000000.00"))


def test_canonical_json_is_sorted_and_compact():
    assert canonical_json({"b": 1, "a": {"d": "x", "c": 2}}) == '{"a":{"c":2,"d":"x"},"b":1}'


def test_intent_hash_is_stable_and_field_sensitive():
    a = ApproveIntent(invoice_fingerprint=FP, limit=Decimal("524300.00"), max_apr_bps=1200, decision_hash=DH)
    b = ApproveIntent(invoice_fingerprint=FP, limit=Decimal("524300.00"), max_apr_bps=1200, decision_hash=DH)
    assert intent_hash(a) == intent_hash(b)
    assert intent_hash(a.model_copy(update={"limit": Decimal("600000.00")})) != intent_hash(a)


def test_intent_rejects_zero_money_and_bad_fingerprint():
    with pytest.raises(ValidationError):
        ApproveIntent(invoice_fingerprint=FP, limit=Decimal("0"), max_apr_bps=1200, decision_hash=DH)
    with pytest.raises(ValidationError):
        ApproveIntent(invoice_fingerprint="fp:1", limit=Decimal("1.00"), max_apr_bps=1200, decision_hash=DH)


def test_guard_result_reports_the_first_block():
    ih = intent_hash(
        ApproveIntent(invoice_fingerprint=FP, limit=Decimal("524300.00"), max_apr_bps=1200, decision_hash=DH)
    )
    blocked = GuardResult(
        intent_hash=ih,
        checks=[
            GuardCheck(layer="L3", code="AprAboveMandate", passed=False),
            GuardCheck(layer="L3", code="AmountAboveLimit", passed=False),
        ],
    )
    assert blocked.passed is False
    assert blocked.block_reason == "AprAboveMandate"
    assert GuardResult(intent_hash=ih, checks=[GuardCheck(layer="L3", code="X", passed=True)]).passed


def test_execute_example_from_the_brief_parses():
    body = {
        "decision": {
            "decision": "approve",
            "advance_rate": 0.70,
            "limit": "524300.00",
            "fee_rate": 0.009,
            "apr": 0.1095,
            "risk_score": 0.003,
            "reasons": [{"code": "BUYER_PAYS_ON_TIME", "message": "Buyer paid 94% of invoices on time"}],
            "decision_id": "dec_01J9Z5",
            "model_version": "pd-lgbm-0.1.0",
            "policy_version": "policy-0.1.0",
            "decision_hash": DH,
        },
        "decision_id": "dec_01J9Z5",
        "decision_hash": DH,
        "invoice_id": "inv_01J9Z4",
        "invoice_fingerprint": FP,
        "doc_hash": "sha256:3f1c",
        "payee": "SELLER:siam-fresh-pack",
        "amount": "524300.00",
        "currency": "THB",
        "apr": 0.1095,
        "lender_id": "lender_a",
        "mandate_id": "mdt_001",
    }
    req = WalletRequest.model_validate(body)
    assert req.amount == Decimal("524300.00")
    assert req.decision.limit == Decimal("524300.00")
