"""Backward-compatible entry point for the OCR-owned end-to-end demo loop."""

from __future__ import annotations

POLICY_FRAUD_REJECT_THRESHOLD = 0.30
POLICY_REVIEW_CONFIDENCE = 0.80


def assess_policy_controls(invoice_payload: dict, policy_decision: dict) -> dict:
    """Compare a real Policy response with the OCR service's documented guards."""
    fraud_score = float(invoice_payload.get("fraud_score", 0.0))
    injection_flags = list(invoice_payload.get("injection_flags") or [])
    confidence = float(invoice_payload.get("confidence", 0.0))
    if fraud_score >= POLICY_FRAUD_REJECT_THRESHOLD:
        expected = "reject"
        reason = "fraud_score_at_or_above_0_30"
    elif injection_flags:
        expected = "review"
        reason = "injection_flags_present"
    elif confidence < POLICY_REVIEW_CONFIDENCE:
        expected = "review"
        reason = "confidence_below_0_80"
    else:
        expected = None
        reason = None
    actual = str(policy_decision.get("decision", "unknown"))
    if expected is None:
        passed, status = None, "not_asserted"
    else:
        passed = actual == expected
        status = "pass" if passed else "control_violation"
    return {
        "expected_decision": expected,
        "actual_decision": actual,
        "trigger": reason,
        "passed": passed,
        "status": status,
        "policy_version": policy_decision.get("policy_version"),
        "model_version": policy_decision.get("model_version"),
    }


def main():
    from demo_loop import main as run_demo_loop

    return run_demo_loop()


if __name__ == "__main__":
    raise SystemExit(main())
