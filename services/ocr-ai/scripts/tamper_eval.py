"""Score PDF edit-trace (tamper) detection on forged and benign invoice PDFs.

Runs the real /ocr/extract pipeline in-process with isolated state (no network, no models)
and applies the documented Policy hard rules to show what each file would reach.

    services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/tamper_eval.py [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from datagen.tamper_corpus import ATTACKS, BENIGN, benign, forge  # noqa: E402

from app.config import Settings  # noqa: E402
from app.pipeline import extract_invoice  # noqa: E402


def gate(response) -> str:
    """Policy hard rules (docs/00-scope.md section 4) plus REVIEW.FRAUD_FLAGS for unknown flags."""
    if response.fraud_score >= 0.30:
        return "reject"
    if response.injection_flags or response.confidence < 0.80 or response.fraud_flags:
        return "review"
    return "approve"


def run(content: bytes, state: Path) -> dict:
    settings = Settings(
        secrets.token_hex(32),
        secrets.token_hex(32),
        state,
        False,
        False,
        "http://127.0.0.1:11434",
        "",
        True,
        False,
    )
    try:
        response = extract_invoice(content, settings, None)
    except HTTPException as exc:
        return {"outcome": f"http_{exc.status_code}", "amount": None, "flags": []}
    return {
        "outcome": gate(response),
        "amount": str(response.amount),
        "flags": [*response.fraud_flags, *response.injection_flags],
        "fraud_score": response.fraud_score,
    }


def evaluate() -> dict:
    rows = []
    with tempfile.TemporaryDirectory(prefix="ocr-tamper-eval-") as folder:
        for index, kind in enumerate(ATTACKS):
            result = run(forge(kind, f"TAMPER-FORGED-{index:04d}"), Path(folder) / f"a{index}.sqlite")
            rows.append({"case": kind, "forged": True, **result})
        for index, kind in enumerate(BENIGN):
            result = run(benign(kind, f"TAMPER-BENIGN-{index:04d}"), Path(folder) / f"b{index}.sqlite")
            rows.append({"case": kind, "forged": False, **result})
    forged = [row for row in rows if row["forged"]]
    clean = [row for row in rows if not row["forged"]]
    return {
        "forged_auto_approved": sum(row["outcome"] == "approve" for row in forged),
        "forged_with_edit_signal": sum(
            any(flag.startswith("pdf_") for flag in row["flags"]) for row in forged
        ),
        "forged_total": len(forged),
        "benign_not_approved": sum(row["outcome"] != "approve" for row in clean),
        "benign_total": len(clean),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = evaluate()
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    print("| case | forged | outcome | amount | flags |")
    print("| --- | --- | --- | --- | --- |")
    for row in report["rows"]:
        print(
            f"| {row['case']} | {row['forged']} | {row['outcome']} | {row['amount']} | "
            f"{', '.join(row['flags'])} |"
        )
    print(
        f"forged auto-approved {report['forged_auto_approved']}/{report['forged_total']}, "
        f"edit signal {report['forged_with_edit_signal']}/{report['forged_total']}, "
        f"benign not approved {report['benign_not_approved']}/{report['benign_total']}"
    )


if __name__ == "__main__":
    main()
