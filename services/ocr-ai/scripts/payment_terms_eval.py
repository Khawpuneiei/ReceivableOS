"""Score the payment-terms check on fictional honest and re-dated invoices.

Runs the real /ocr/extract pipeline in-process with isolated state (no network, no models).

    services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/payment_terms_eval.py
"""

from __future__ import annotations

import secrets
import sys
import tempfile
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from datagen.payment_terms import CASES, case_pdf  # noqa: E402

from app.config import Settings  # noqa: E402
from app.pipeline import extract_invoice  # noqa: E402


def gate(response) -> str:
    """Policy's hard rules, applied to the OCR response alone."""
    if response.fraud_score >= 0.30:
        return "reject"
    if response.injection_flags or response.confidence < 0.80 or response.fraud_flags:
        return "review"
    return "approve"


def main() -> None:
    passed = 0
    print("| case | due date | expected | flagged | outcome |")
    print("| --- | --- | --- | --- | --- |")
    with tempfile.TemporaryDirectory(prefix="ocr-terms-eval-") as folder:
        for index, (name, (*_, expected)) in enumerate(CASES.items()):
            settings = Settings(
                secrets.token_hex(32), secrets.token_hex(32), Path(folder) / f"{index}.sqlite",
                False, False, "", "", True, False,
            )  # fmt: skip
            response = extract_invoice(case_pdf(name, f"TERMS-EVAL-{index:04d}"), settings, None)
            flagged = "DUE_DATE_TERMS_MISMATCH" in response.validation_flags
            outcome = gate(response)
            passed += flagged == expected and outcome == ("review" if expected else "approve")
            print(
                f"| {name} | {response.due_date} | {'flag' if expected else 'ok'} | {flagged} | {outcome} |"
            )
    print(f"{passed}/{len(CASES)} cases flagged as expected with the expected outcome")


if __name__ == "__main__":
    main()
