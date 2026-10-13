"""Score the amount-in-words cross-check on fictional honest and regenerated invoices.

Runs the real /ocr/extract pipeline in-process with isolated state (no network, no models).

    services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/amount_words_eval.py
"""

from __future__ import annotations

import secrets
import sys
import tempfile
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from datagen.amount_words import CASES, case_pdf  # noqa: E402

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
    print("| case | amount (digits) | expected | flagged | outcome |")
    print("| --- | --- | --- | --- | --- |")
    with tempfile.TemporaryDirectory(prefix="ocr-words-eval-") as folder:
        for index, (name, (_, _, expected)) in enumerate(CASES.items()):
            settings = Settings(
                secrets.token_hex(32), secrets.token_hex(32), Path(folder) / f"{index}.sqlite",
                False, False, "", "", True, False,
            )  # fmt: skip
            response = extract_invoice(case_pdf(name, f"WORDS-EVAL-{index:04d}"), settings, None)
            flagged = "AMOUNT_WORDS_MISMATCH" in response.validation_flags
            outcome = gate(response)
            passed += flagged == expected and outcome == ("review" if expected else "approve")
            print(
                f"| {name} | {response.amount} | {'flag' if expected else 'clean'} | {flagged} | {outcome} |"
            )
    print(f"{passed}/{len(CASES)} cases flagged as expected with the expected outcome")


if __name__ == "__main__":
    main()
