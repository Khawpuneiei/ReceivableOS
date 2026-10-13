"""Score the scoped amount-outlier signal on fictional supplier-buyer invoice sequences.

For each case, four ordinary invoices are observed first, then the case invoice. Runs the real
/ocr/extract pipeline in-process with isolated state (no network, no models).

    services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/amount_history_eval.py
"""

from __future__ import annotations

import secrets
import sys
import tempfile
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from datagen.amount_history import CASES, HISTORY, invoice  # noqa: E402

from app.config import Settings  # noqa: E402
from app.pipeline import extract_invoice  # noqa: E402


def gate(response) -> str:
    """Policy's hard rules, applied to the OCR response alone."""
    if response.fraud_score >= 0.30:
        return "reject"
    if response.injection_flags or response.confidence < 0.80 or response.fraud_flags:
        return "review"
    return "approve"


def run_case(name: str, folder: Path):
    quantity, other_buyer, _ = CASES[name]
    settings = Settings(
        secrets.token_hex(32), secrets.token_hex(32), folder / f"{name}.sqlite",
        False, False, "", "", True, False,
    )  # fmt: skip
    for index, (history_quantity, issue) in enumerate(HISTORY):
        extract_invoice(invoice(history_quantity, f"HIST-{index:04d}", issue), settings, None)
    return extract_invoice(
        invoice(quantity, "HIST-CASE", "2026-10-01", other_buyer=other_buyer), settings, None
    )


def main() -> None:
    passed = 0
    print("| case | amount | expected | observed | outcome |")
    print("| --- | --- | --- | --- | --- |")
    with tempfile.TemporaryDirectory(prefix="ocr-history-eval-") as folder:
        for name, (*_, expected) in CASES.items():
            response = run_case(name, Path(folder))
            observed = "amount_outlier" in response.fraud_flags
            outcome = gate(response)
            passed += observed == expected and outcome == ("review" if expected else "approve")
            print(f"| {name} | {response.amount} | {expected} | {observed} | {outcome} |")
    print(f"{passed}/{len(CASES)} cases match the expected outlier finding and outcome")


if __name__ == "__main__":
    main()
