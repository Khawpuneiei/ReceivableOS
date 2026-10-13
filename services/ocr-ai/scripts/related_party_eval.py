"""Score the related-party checks on fictional invoice sequences.

Each case observes its earlier invoices first, then a 749,000 THB invoice dated 2026-10-01.
Runs the real /ocr/extract pipeline in-process with isolated state (no network, no models).

    services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/related_party_eval.py
"""

from __future__ import annotations

import secrets
import sys
import tempfile
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from datagen.related_party import CASES, invoice  # noqa: E402

from app.config import Settings  # noqa: E402
from app.pipeline import extract_invoice  # noqa: E402

FLAGS = ("SUPPLIER_IS_BUYER", "circular_invoicing")


def gate(response) -> str:
    """Policy's hard rules, applied to the OCR response alone."""
    if response.fraud_score >= 0.30:
        return "reject"
    if response.injection_flags or response.confidence < 0.80 or response.fraud_flags:
        return "review"
    return "approve"


def run_case(name: str, folder: Path):
    earlier, final, _ = CASES[name]
    settings = Settings(
        secrets.token_hex(32), secrets.token_hex(32), folder / f"{name}.sqlite",
        False, False, "", "", True, False,
    )  # fmt: skip
    for index, (quantity, issue, reverse) in enumerate(earlier):
        extract_invoice(invoice(quantity, f"RP-PRIOR-{index:04d}", issue, reverse=reverse), settings, None)
    return extract_invoice(invoice(50_000, "RP-CASE-0001", "2026-10-01", **final), settings, None)


def main() -> None:
    passed = 0
    print("| case | expected | observed | outcome |")
    print("| --- | --- | --- | --- |")
    with tempfile.TemporaryDirectory(prefix="ocr-related-eval-") as folder:
        for name, (*_, expected) in CASES.items():
            response = run_case(name, Path(folder))
            observed = [flag for flag in (*response.validation_flags, *response.fraud_flags) if flag in FLAGS]
            outcome = gate(response)
            passed += observed == ([expected] if expected else []) and outcome == (
                "review" if expected else "approve"
            )
            print(f"| {name} | {expected or '-'} | {', '.join(observed) or '-'} | {outcome} |")
    print(f"{passed}/{len(CASES)} cases match the expected related-party finding and outcome")


if __name__ == "__main__":
    main()
