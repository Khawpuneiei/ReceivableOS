"""Terms and pricing (brief section 6.2): demo numbers, every haircut and cap, clamps and a property test."""

import io
import random
import tokenize
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from factories import AS_OF, ctx_for, edited_rules, happy_body

from app import model
from app.engine import evaluate, merge_outcome
from app.profiles import normalise_buyer, normalise_supplier
from app.rules import active_rules
from app.schemas import Mandate
from app.terms import compute_terms, fmt_rate, price
from shared.schemas import Decision

RULES = active_rules()


def _evaluate(body: dict, rules=None):
    ctx, results = evaluate(ctx_for(body, rules))
    return ctx, {r.id: r for r in results}


def _hit_ids(results: dict) -> set[str]:
    return {i for i, r in results.items() if r.status == "hit"}


def _codes(ctx) -> list[str]:
    return [s.code for s in ctx.terms.steps]


def _fixed_pd(monkeypatch, pd: float) -> None:
    monkeypatch.setattr(model, "predict_pd", lambda buyer, tenor_days: pd)


# --- The shared demo (brief 6.2 worked example) ---


def test_happy_path_terms_and_price():
    ctx, results = _evaluate(happy_body())
    assert merge_outcome(results.values()) == Decision.approve
    assert ctx.terms.advance_rate == Decimal("0.70")
    assert str(ctx.terms.limit) == "524300.00"
    assert _codes(ctx) == ["TERMS.MANDATE_CAP"]
    assert ctx.terms.steps[0].effect == "advance_rate 0.80 -> 0.70"
    assert ctx.price.fee_rate == Decimal("0.009")
    assert ctx.price.apr == Decimal("0.1095")
    assert ctx.price.fee_amount == Decimal("5347.86")
    assert ctx.price.expected_loss == (ctx.pd * RULES.lgd * ctx.terms.limit).quantize(Decimal("0.01"))


def test_worked_example_price_at_pd_0_003():
    p = price(RULES, pd=Decimal("0.003"), tenor_days=34, confirmed=True, limit=Decimal("524300.00"))
    assert p.annual.quantize(Decimal("0.0001")) == Decimal("0.1082")
    assert p.fee_rate == Decimal("0.009")
    assert p.apr == Decimal("0.1095")
    assert p.fee_amount == Decimal("5347.86")
    assert p.expected_loss == Decimal("707.81")


def test_without_a_mandate_tier_a_gets_0_80():
    body = happy_body()
    del body["mandate"]
    ctx, _ = _evaluate(body)
    assert (ctx.terms.advance_rate, ctx.terms.limit) == (Decimal("0.80"), Decimal("599200.00"))
    assert _codes(ctx) == []


def test_unconfirmed_buyer_v3():
    body = happy_body()
    body["buyer_profile"]["buyer_confirmed"] = False
    ctx, results = _evaluate(body)
    assert (ctx.terms.advance_rate, ctx.terms.limit) == (Decimal("0.60"), Decimal("449400.00"))
    assert "TERMS.HAIRCUT_UNCONFIRMED" in _codes(ctx)
    assert ctx.price.annual == pytest.approx(Decimal("0.143"), abs=Decimal("0.001"))
    assert ctx.price.fee_rate == Decimal("0.012")
    assert {"REVIEW.UNCONFIRMED_BUYER", "REVIEW.MANDATE_APR"} <= _hit_ids(results)
    assert "KO.PRICING" not in _hit_ids(results)
    assert merge_outcome(results.values()) == Decision.review


# --- Haircuts, each at its boundary ---


def _no_mandate(**invoice) -> dict:
    body = happy_body()
    del body["mandate"]
    body["invoice"].update(invoice)
    return body


@pytest.mark.parametrize(
    ("code", "field", "fires", "holds"),
    [
        ("TERMS.HAIRCUT_TENOR", "due_date", AS_OF + timedelta(91), AS_OF + timedelta(90)),
        ("TERMS.HAIRCUT_AGE", "issue_date", AS_OF - timedelta(61), AS_OF - timedelta(60)),
    ],
)
def test_date_haircuts(code, field, fires, holds):
    ctx, _ = _evaluate(_no_mandate(**{field: fires.isoformat()}))
    assert code in _codes(ctx) and ctx.terms.advance_rate == Decimal("0.75")
    assert code not in _codes(_evaluate(_no_mandate(**{field: holds.isoformat()}))[0])


def test_dilution_haircut():
    body = _no_mandate()
    body["supplier_profile"]["dilution_rate"] = 0.051
    ctx, _ = _evaluate(body)
    assert "TERMS.HAIRCUT_DILUTION" in _codes(ctx) and ctx.terms.advance_rate == Decimal("0.75")
    body["supplier_profile"]["dilution_rate"] = 0.05
    assert "TERMS.HAIRCUT_DILUTION" not in _codes(_evaluate(body)[0])
    del body["supplier_profile"]["dilution_rate"]
    assert _evaluate(body)[1]["TERMS.HAIRCUT_DILUTION"].trace == "TERMS.HAIRCUT_DILUTION:skip(missing)"


def test_pd_haircut(monkeypatch):
    _fixed_pd(monkeypatch, 0.031)
    ctx, _ = _evaluate(_no_mandate())
    assert "TERMS.HAIRCUT_PD" in _codes(ctx) and ctx.terms.advance_rate == Decimal("0.75")
    _fixed_pd(monkeypatch, 0.03)
    assert "TERMS.HAIRCUT_PD" not in _codes(_evaluate(_no_mandate())[0])


def test_floor():
    body = _no_mandate(due_date=(AS_OF + timedelta(100)).isoformat())
    body["buyer_profile"].update(internal_rating="BB", buyer_confirmed=False)
    ctx, _ = _evaluate(body)  # 0.65 - 0.20 - 0.05 = 0.40, raised to the 0.50 floor
    assert ctx.terms.tier == "C"
    assert ctx.terms.steps[-1].code == "TERMS.FLOOR"
    assert ctx.terms.steps[-1].effect == "advance_rate 0.40 -> 0.50"
    assert ctx.terms.advance_rate == Decimal("0.50")


def test_thin_profile_uses_tier_c():
    body = _no_mandate()
    del body["buyer_profile"]["internal_rating"]
    ctx, _ = _evaluate(body)
    assert (ctx.terms.tier, ctx.terms.advance_rate) == ("C", Decimal("0.65"))


# --- Caps ---


def test_buyer_limit_cap():
    body = _no_mandate()
    body["buyer_profile"]["buyer_limit"] = "300000.00"
    ctx, _ = _evaluate(body)
    assert "TERMS.CAP_BUYER_LIMIT" in _codes(ctx)
    assert ctx.terms.limit <= Decimal("300000.00")
    assert abs(ctx.terms.advance_rate * Decimal("749000.00") - ctx.terms.limit) <= Decimal("0.01")


def test_facility_cap_and_headroom_reason():
    body = _no_mandate()
    body["supplier_profile"]["current_exposure"] = "2900000.00"
    ctx, results = _evaluate(body)
    assert ctx.terms.limit == Decimal("99991.50")  # rate floor(100000 / 749000, 4 dp) = 0.1335
    assert {"TERMS.HEADROOM", "TERMS.CAP_FACILITY"} <= set(_codes(ctx))
    assert "facility headroom 100000.00" in [s.effect for s in ctx.terms.steps]


def test_single_invoice_cap_per_currency():
    body = _no_mandate(currency="USD", amount="200000.00", line_items=[])
    ctx, _ = _evaluate(body)
    assert "TERMS.CAP_SINGLE_INVOICE" in _codes(ctx)
    assert ctx.terms.limit == Decimal("90000.00")


def test_mandate_per_transaction_cap():
    body = happy_body()
    body["mandate"]["max_amount_per_tx"] = "400000.00"
    ctx, _ = _evaluate(body)
    assert _codes(ctx) == ["TERMS.MANDATE_CAP", "TERMS.CAP_MANDATE_TX"]
    assert ctx.terms.limit <= Decimal("400000.00")


def test_no_headroom_rejects():
    body = happy_body()
    body["supplier_profile"]["current_exposure"] = "3000000.00"
    ctx, results = _evaluate(body)
    assert (results["KO.NO_HEADROOM"].status, results["KO.NO_HEADROOM"].outcome) == ("hit", "reject")
    assert (ctx.terms.advance_rate, str(ctx.terms.limit)) == (Decimal(0), "0.00")


def test_tier_d_gets_no_terms_and_terms_rules_skip():
    body = happy_body()
    body["buyer_profile"]["internal_rating"] = "B"
    ctx, results = _evaluate(body)
    assert ctx.terms is None
    assert results["KO.NO_HEADROOM"].trace == "KO.NO_HEADROOM:skip(missing)"
    assert merge_outcome(results.values()) == Decision.reject


# --- Pricing ---


def test_risk_price_above_the_legal_ceiling_rejects(monkeypatch):
    _fixed_pd(monkeypatch, 0.02)  # 0.10 + 0.02 x 0.45 x 365/60 = 0.1548 > 0.15
    _, results = _evaluate(happy_body())
    assert (results["KO.PRICING"].status, results["KO.PRICING"].outcome) == ("hit", "reject")
    _fixed_pd(monkeypatch, 0.018)  # 0.1493
    assert "KO.PRICING" not in _hit_ids(_evaluate(happy_body())[1])


def test_fee_is_clamped_to_the_yaml_range(tmp_path):
    high = price(RULES, pd=Decimal("0.10"), tenor_days=34, confirmed=False, limit=Decimal("1000.00"))
    assert high.fee_rate == RULES.pricing.max_fee_rate
    assert high.annual > Decimal("0.15")
    cheap = edited_rules(tmp_path, lambda raw: raw["pricing"].update(cost_of_funds=0.0, margin=0.01))
    low = price(cheap, pd=Decimal("0.0001"), tenor_days=34, confirmed=True, limit=Decimal("1000.00"))
    assert low.fee_rate == cheap.pricing.min_fee_rate


def test_mandate_apr_cap_reviews():
    body = happy_body()
    body["mandate"]["max_apr"] = "0.10"  # 0.009 x 365/30 = 10.95% > 10%
    assert "REVIEW.MANDATE_APR" in _hit_ids(_evaluate(body)[1])


def test_concentration_reviews_against_the_pool():
    body = happy_body()
    body["portfolio"] = {"total_exposure": "0.00", "pool_capacity": "1000000.00"}
    r = _evaluate(body)[1]["REVIEW.CONCENTRATION"]
    assert (r.status, r.outcome) == ("hit", "review")
    body["portfolio"]["pool_capacity"] = "100000000.00"
    assert "REVIEW.CONCENTRATION" not in _hit_ids(_evaluate(body)[1])


def test_rate_formatting():
    assert str(fmt_rate(Decimal("0.7000"))) == "0.70"
    assert str(fmt_rate(Decimal("0.0090"))) == "0.009"
    assert str(fmt_rate(Decimal("0.1095"))) == "0.1095"
    assert str(fmt_rate(Decimal("0"))) == "0.00"


# --- Invariants ---


def test_property_limit_never_exceeds_a_cap():
    rng = random.Random(42)
    haircuts = list(RULES.terms.haircuts)
    for _ in range(500):
        amount = Decimal(rng.randint(1_000_00, 6_000_000_00)) / 100
        currency = rng.choice(["THB", "USD"])
        buyer = normalise_buyer(
            {
                "buyer_limit": str(rng.randint(0, 5_000_000)),
                "current_exposure": str(rng.randint(0, 3_000_000)),
            }
        )
        supplier = normalise_supplier(
            {
                "facility_limit": str(rng.randint(0, 4_000_000)),
                "current_exposure": str(rng.randint(0, 3_000_000)),
            }
        )
        mandate = rng.choice(
            [
                None,
                Mandate(
                    max_ltv=Decimal(rng.randint(10, 90)) / 100, max_amount_per_tx=rng.randint(1, 2_000_000)
                ),
            ]
        )
        t = compute_terms(
            RULES,
            tier=rng.choice("ABC"),
            amount=amount,
            currency=currency,
            haircuts=rng.sample(haircuts, rng.randint(0, len(haircuts))),
            buyer=buyer,
            supplier=supplier,
            mandate=mandate,
        )
        caps = [
            buyer.buyer_limit - buyer.current_exposure,
            supplier.facility_limit - supplier.current_exposure,
            RULES.terms.max_single_invoice_limit[currency],
            t.advance * amount,
        ]
        if mandate is not None:
            caps.append(mandate.max_amount_per_tx)
        assert t.limit <= max(min(caps), Decimal(0))
        assert Decimal(0) <= t.advance_rate <= Decimal(1)
        assert abs(t.advance_rate * amount - t.limit) <= Decimal("0.01")
        pd = Decimal(rng.randint(0, 2000)) / 10000
        p = price(RULES, pd=pd, tenor_days=rng.randint(7, 120), confirmed=rng.random() < 0.7, limit=t.limit)
        assert RULES.pricing.min_fee_rate <= p.fee_rate <= RULES.pricing.max_fee_rate


def test_no_numbers_hard_coded_in_terms_or_engine():
    allowed = {"0", "1", "30", "365"}
    for name in ("terms.py", "engine.py"):
        source = (Path(__file__).resolve().parents[1] / "app" / name).read_text(encoding="utf-8")
        numbers = {
            t.string
            for t in tokenize.generate_tokens(io.StringIO(source).readline)
            if t.type == tokenize.NUMBER
        }
        assert numbers <= allowed, (name, numbers - allowed)
