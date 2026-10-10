from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import Mandate, PolicyDecisionExt, PolicyRequestExt, ReasonDetail
from shared.schemas import PolicyDecision, PolicyRequest

INVOICE = {
    "invoice_id": "inv_sfp_0142",
    "supplier": {"name": "Siam Fresh Pack Co., Ltd.", "tax_id": "0105559000000"},
    "buyer": {"name": "Mekong Basket Retail PCL", "tax_id": "0107559000001"},
    "invoice_no": "SFP-INV-2026-0142",
    "issue_date": "2026-10-01",
    "due_date": "2026-11-15",
    "amount": "749000.00",
    "currency": "THB",
    "line_items": [
        {"description": "Food trays", "qty": "50000", "unit_price": "14.00", "total": "700000.00"},
    ],
    "confidence": 0.95,
    "injection_flags": [],
    "fraud_score": 0.07,
    "fraud_flags": [],
    "doc_hash": "sha256:" + "ab" * 32,
    "invoice_fingerprint": "0x" + "cd" * 32,
}

# The agent wallet's demo mandate (its CLAUDE.md 5.2), including wallet-only keys.
WALLET_MANDATE = {
    "mandate_id": "mdt_001",
    "version": 1,
    "max_ltv": "0.70",
    "max_apr": "0.12",
    "max_predicted_default": "0.05",
    "max_amount_per_tx": "1500000.00",
    "daily_cap": "3000000.00",
    "allowed_currency": "THB",
    "settlement_asset": "tTHB",
    "require_kyb": True,
    "require_buyer_attestation": True,
    "duplicate_policy": "DENY",
    "human_review_above": "837500.00",
    "payee_allowlist": ["SELLER:siam-fresh-pack"],
    "allowed_targets": ["FinancingVault", "ReceivableRegistry"],
    "valid_from": "2026-10-10T00:00:00+07:00",
    "expires_at": "2026-11-30T23:59:59+07:00",
    "approved_by": "P",
}


def _decision() -> PolicyDecisionExt:
    return PolicyDecisionExt(
        decision="approve",
        advance_rate=Decimal("0.70"),
        limit=Decimal("524300.00"),
        fee_rate=Decimal("0.009"),
        apr=Decimal("0.1095"),
        risk_score=0.0029,
        pd=0.0029,
        reasons=["TERMS.MANDATE_CAP: advance capped by the mandate"],
        model_version="scorecard-fallback",
        policy_version="credit-policy-v0.1",
        decision_id="dec_0123456789abcdef01234567",
        decision_hash="0x" + "00" * 32,
        expected_loss=Decimal("684.21"),
        tenor_days=34,
        fee_amount=Decimal("5347.86"),
        reason_details=[
            ReasonDetail(
                code="TERMS.MANDATE_CAP",
                message="advance capped by the mandate",
                source="rule",
                effect="advance_rate 0.80 -> 0.70",
            )
        ],
        top_features=[{"feature": "buyer_tier_ord", "value": 0.0, "contribution": -0.6}],
        rule_trace=["HARD.FRAUD_SCORE:pass"],
        valid_until=datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc),
        as_of_date=date(2026, 10, 12),
        request_hash="0x" + "11" * 32,
    )


def test_ext_models_subclass_the_shared_contract():
    assert issubclass(PolicyRequestExt, PolicyRequest)
    assert issubclass(PolicyDecisionExt, PolicyDecision)


def test_shared_fields_are_not_redeclared():
    for name, field in PolicyDecision.model_fields.items():
        assert PolicyDecisionExt.model_fields[name].annotation == field.annotation, name
    for name, field in PolicyRequest.model_fields.items():
        assert PolicyRequestExt.model_fields[name].annotation == field.annotation, name


def test_decision_ext_dump_validates_as_shared_decision():
    body = _decision().model_dump(mode="json")
    shared = PolicyDecision.model_validate(body)
    assert shared.decision.value == "approve"
    assert shared.limit == Decimal("524300.00")
    assert shared.apr == Decimal("0.1095")
    assert shared.decision_hash == "0x" + "00" * 32
    assert body["limit"] == "524300.00"  # money stays a decimal string in JSON
    assert body["reason_details"][0]["source"] == "rule"


def test_plain_request_validates_as_ext():
    plain = PolicyRequest.model_validate({"invoice": INVOICE}).model_dump(mode="json")
    req = PolicyRequestExt.model_validate(plain)
    assert req.mandate is None and req.portfolio is None and req.as_of_date is None
    assert req.invoice.amount == Decimal("749000.00")


def test_request_with_extras():
    req = PolicyRequestExt.model_validate(
        {
            "invoice": INVOICE,
            "mandate": WALLET_MANDATE,
            "portfolio": {"total_exposure": "0.00", "pool_capacity": "100000000.00"},
            "as_of_date": "2026-10-12",
        }
    )
    assert req.as_of_date == date(2026, 10, 12)
    assert req.portfolio.pool_capacity == Decimal("100000000.00")
    assert req.mandate.max_ltv == Decimal("0.70")


def test_wallet_mandate_parses_and_ignores_wallet_only_keys():
    m = Mandate.model_validate(WALLET_MANDATE)
    assert m.mandate_id == "mdt_001"
    assert m.max_ltv == Decimal("0.70")
    assert m.max_apr == Decimal("0.12")
    assert m.max_predicted_default == Decimal("0.05")
    assert m.human_review_above == Decimal("837500.00")
    assert m.max_amount_per_tx == Decimal("1500000.00")
    assert m.daily_cap == Decimal("3000000.00")
    assert m.allowed_currency == "THB"
    assert m.expires_at.isoformat() == "2026-11-30T23:59:59+07:00"
    assert "payee_allowlist" not in m.model_dump()


def test_mandate_accepts_wallet_aliases():
    m = Mandate.model_validate(
        {"max_advance_rate": 0.7, "max_pd": "0.05", "human_review_above_thb": "837500.00", "currency": "THB"}
    )
    assert m.max_ltv == Decimal("0.7")
    assert m.max_predicted_default == Decimal("0.05")
    assert m.human_review_above == Decimal("837500.00")
    assert m.allowed_currency == "THB"


def test_empty_mandate_constrains_nothing():
    m = Mandate.model_validate({})
    assert m.max_ltv is None and m.max_apr is None and m.max_amount_per_tx is None


@pytest.mark.parametrize(
    "bad",
    [
        {"max_ltv": 0},
        {"max_ltv": "1.5"},
        {"max_pd": -0.01},
        {"human_review_above": "0"},
        {"currency": "BAHT"},
    ],
)
def test_malformed_mandate_is_rejected(bad):
    with pytest.raises(ValidationError):
        Mandate.model_validate(bad)


def test_portfolio_needs_positive_capacity():
    with pytest.raises(ValidationError):
        PolicyRequestExt.model_validate({"invoice": INVOICE, "portfolio": {"pool_capacity": "0"}})
