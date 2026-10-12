"""Policy-contract checks used by the OCR-owned demo loop report."""

from scripts.smoke_integration import assess_policy_controls


def test_injection_requires_policy_review():
    result = assess_policy_controls(
        {"confidence": 0.97, "fraud_score": 0.0, "injection_flags": ["VISIBLE_INSTRUCTION"]},
        {"decision": "review"},
    )

    assert result["expected_decision"] == "review"
    assert result["passed"] is True


def test_high_fraud_score_requires_policy_rejection():
    result = assess_policy_controls(
        {"confidence": 0.97, "fraud_score": 0.7, "injection_flags": []},
        {"decision": "reject"},
    )

    assert result["expected_decision"] == "reject"
    assert result["passed"] is True


def test_policy_stub_approval_is_reported_as_a_control_violation():
    result = assess_policy_controls(
        {"confidence": 0.97, "fraud_score": 0.7, "injection_flags": []},
        {"decision": "approve"},
    )

    assert result["expected_decision"] == "reject"
    assert result["actual_decision"] == "approve"
    assert result["passed"] is False
    assert result["status"] == "control_violation"


def test_unresolved_confidence_requires_policy_review():
    result = assess_policy_controls(
        {"confidence": 0.79, "fraud_score": 0.0, "injection_flags": []},
        {"decision": "review"},
    )

    assert result["expected_decision"] == "review"
    assert result["passed"] is True


def test_clean_invoice_has_no_policy_hard_stop_assertion():
    result = assess_policy_controls(
        {"confidence": 0.97, "fraud_score": 0.0, "injection_flags": []},
        {"decision": "approve"},
    )

    assert result["expected_decision"] is None
    assert result["passed"] is None
    assert result["status"] == "not_asserted"
