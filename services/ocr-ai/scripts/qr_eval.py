"""Score the Thai payment-QR cross-check on fictional matching and swapped QR codes.

Runs the real /ocr/extract pipeline in-process with isolated state (no network, no models).

    services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/qr_eval.py
"""

from __future__ import annotations

import secrets
import sys
import tempfile
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from datagen.thai_qr import CASES, case_pdf  # noqa: E402

from app.config import Settings  # noqa: E402
from app.pipeline import extract_invoice  # noqa: E402


def gate(response) -> str:
    if response.fraud_score >= 0.30:
        return "reject"
    if response.injection_flags or response.confidence < 0.80 or response.fraud_flags:
        return "review"
    return "approve"


def main() -> None:
    passed = 0
    print("| case | expected flags | observed flags | outcome |")
    print("| --- | --- | --- | --- |")
    with tempfile.TemporaryDirectory(prefix="ocr-qr-eval-") as folder:
        for index, (name, (_, expected)) in enumerate(CASES.items()):
            settings = Settings(
                secrets.token_hex(32), secrets.token_hex(32), Path(folder) / f"{index}.sqlite",
                False, False, "", "", True, False,
            )  # fmt: skip
            response = extract_invoice(case_pdf(name, f"QR-EVAL-{index:04d}"), settings, None)
            observed = {flag for flag in response.fraud_flags if flag.startswith("qr_")}
            passed += observed == expected
            print(f"| {name} | {', '.join(sorted(expected)) or '-'} | {', '.join(sorted(observed)) or '-'} | "
                  f"{gate(response)} |")  # fmt: skip
    print(f"{passed}/{len(CASES)} cases match the expected QR findings")


if __name__ == "__main__":
    main()
