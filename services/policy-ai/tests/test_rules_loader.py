import copy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app import rules as rules_module
from app.rules import DEFAULT_RULES_PATH, RegistryError, active_rules, check_registry, load_rules

RAW = yaml.safe_load(DEFAULT_RULES_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, raw: dict) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def _edited(edit) -> dict:
    raw = copy.deepcopy(RAW)
    edit(raw)
    return raw


def _by_id(section: list[dict], rule_id: str) -> dict:
    return next(r for r in section if r["id"] == rule_id)


def test_rule_set_loads():
    r = load_rules()
    assert r.version == "credit-policy-v0.1"
    assert r.currency_allowlist == ["THB", "USD"]
    assert r.decision_ttl_hours == 24
    assert active_rules().version == r.version


def test_key_numbers_are_exact_decimals():
    r = load_rules()
    assert r.rule("HARD.FRAUD_SCORE").param.min_fraud_score == Decimal("0.30")
    assert r.rule("HARD.LOW_CONFIDENCE").param.min_confidence == Decimal("0.80")
    assert r.lgd == Decimal("0.45")
    assert r.terms.base_advance_by_tier == {"A": Decimal("0.80"), "B": Decimal("0.75"), "C": Decimal("0.65")}
    assert r.pricing.max_fee_rate == Decimal("0.0123")
    assert r.pricing.fee_step == Decimal("0.0005")
    assert r.rule("KO.PRICING").param.max_apr == Decimal("0.15")
    assert r.rule("KO.PD_TOO_HIGH").param.reject_above == Decimal("0.15")
    assert r.rule("REVIEW.PD_ABOVE_CAP").param.review_above == Decimal("0.05")
    assert r.rule("KO.TENOR_TOO_SHORT").param.min_tenor_days == 7
    assert r.defaults.human_review_above["THB"] == Decimal("837500.00")
    assert "0xSUPPLIER" in r.mandate_limits.payee_registry["SELLER:siam-fresh-pack"]


def test_outcomes():
    r = load_rules()
    assert r.rule("HARD.FRAUD_SCORE").outcome == "reject"
    assert r.rule("HARD.INJECTION").outcome == "review"
    assert {k.outcome for k in r.knockouts} == {"reject"}
    assert {t.outcome for t in r.review_triggers} == {"review"}
    assert [(g.id, g.outcome) for g in r.pd_gates] == [
        ("KO.PD_TOO_HIGH", "reject"),
        ("REVIEW.PD_ABOVE_CAP", "review"),
    ]


def test_both_flag_spellings_are_listed():
    r = load_rules()
    assert set(r.rule("KO.DUPLICATE").param.flags) == {
        "duplicate_invoice_hash",
        "duplicate_fingerprint",
        "DUPLICATE_HASH",
        "DUPLICATE_INVOICE",
    }
    assert set(r.rule("KO.PO_MISMATCH").param.flags) == {"po_amount_mismatch", "PO_MISMATCH"}


def test_large_ticket_review_is_off_by_default():
    param = load_rules().rule("REVIEW.LARGE_TICKET").param
    assert param.enabled is False
    assert param.basis == "amount"


def test_finance_tbd_markers_kept():
    assert DEFAULT_RULES_PATH.read_text(encoding="utf-8").count("FINANCE-TBD") >= 8


@pytest.mark.parametrize(
    "edit",
    [
        lambda raw: raw.update(lgdd=0.45),  # typo at the top level
        lambda raw: raw["terms"].update(floor_advanc=0.5),  # typo in a section
        lambda raw: _by_id(raw["hard_rules"], "HARD.FRAUD_SCORE").update(param={"min_fraud_scor": 0.3}),
        lambda raw: _by_id(raw["hard_rules"], "HARD.INJECTION").update(param={"threshold": 1}),
        lambda raw: _by_id(raw["knockouts"], "KO.TENOR_TOO_SHORT").update(param={}),  # required param missing
        lambda raw: _by_id(raw["knockouts"], "KO.BUYER_TIER").update(param={"ineligible": ["E"]}),
        lambda raw: raw.update(lgd=1.5),
        lambda raw: raw["pricing"].update(min_fee_rate=0.02),  # above max_fee_rate
        lambda raw: raw["terms"]["base_advance_by_tier"].pop("C"),
        lambda raw: raw["defaults"]["pool_capacity"].pop("USD"),  # allowlisted currency without a value
        lambda raw: raw["defaults"]["human_review_above"].update(THB="837500.001"),  # more than 2 dp
        lambda raw: raw["mandate_limits"]["defaults"].update(max_ltv=0.95),  # default above platform max
        lambda raw: raw["mandate_limits"]["defaults"]["daily_cap"].update(THB="4000000.00"),
        lambda raw: raw["hard_rules"][0].pop("outcome"),  # HARD.* must state its outcome
        lambda raw: raw["knockouts"][0].update(outcome="review"),  # KO.* always rejects
        lambda raw: raw["knockouts"].append({"id": "REVIEW.X", "message": "wrong section"}),
        lambda raw: raw["review_triggers"].append(dict(raw["review_triggers"][0])),  # duplicate id
        lambda raw: raw["terms"]["haircuts"].append({"id": "TERMS.FLOOR2", "minus": 0.1, "message": "m"}),
        lambda raw: raw.update(version="v1"),
        lambda raw: _by_id(raw["review_triggers"], "REVIEW.THIN_PROFILE").update(param={"terms_tier": "D"}),
    ],
)
def test_invalid_rule_sets_fail_at_load(tmp_path, edit):
    with pytest.raises(ValidationError):
        load_rules(_write(tmp_path, _edited(edit)))


def test_non_mapping_yaml_fails(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_rules(path)


def test_env_override_selects_the_rule_file(tmp_path, monkeypatch):
    path = _write(tmp_path, _edited(lambda raw: raw.update(version="credit-policy-v9.9")))
    monkeypatch.setenv(rules_module.RULES_PATH_ENV, str(path))
    assert load_rules().version == "credit-policy-v9.9"
    active_rules.cache_clear()
    try:
        assert active_rules().version == "credit-policy-v9.9"
    finally:
        monkeypatch.delenv(rules_module.RULES_PATH_ENV)
        active_rules.cache_clear()
    assert active_rules().version == "credit-policy-v0.1"


def test_registry_must_match_the_yaml():
    r = load_rules()
    registry = {rule_id: object() for rule_id in r.rule_ids()}
    check_registry(r, registry)  # exact match passes

    without_one = {k: v for k, v in registry.items() if k != "KO.DUPLICATE"}
    with pytest.raises(RegistryError, match="no predicate for.*KO.DUPLICATE"):
        check_registry(r, without_one)

    with pytest.raises(RegistryError, match="no YAML entry for.*KO.NOT_IN_YAML"):
        check_registry(r, [*registry, "KO.NOT_IN_YAML"])


def test_rule_ids_follow_evaluation_order():
    ids = load_rules().rule_ids()
    first = {
        prefix: next(i for i, rule_id in enumerate(ids) if rule_id.startswith(prefix))
        for prefix in ("HARD.", "KO.", "REVIEW.", "TERMS.")
    }
    assert first["HARD."] < first["KO."] < first["REVIEW."] < first["TERMS."]
    with pytest.raises(KeyError):
        load_rules().rule("KO.UNKNOWN")


def test_loader_never_evaluates_yaml():
    source = Path(rules_module.__file__).read_text(encoding="utf-8")
    assert "eval(" not in source and "exec(" not in source
    assert "yaml.safe_load" in source and "yaml.load(" not in source
