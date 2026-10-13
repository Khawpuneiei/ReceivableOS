"""Score OCR-side prompt-injection detection on paraphrased, multilingual and obfuscated payloads.

Runs the real parser and extractor in-process on synthetic PDFs (no network, no models).
Attack recall = share of attack PDFs that raise any injection flag.
Benign false-positive rate = share of hard-negative PDFs that raise a flag or lose a field.

    services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/injection_eval.py [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from datagen.injection_payloads import attack_cases, benign_cases, inject  # noqa: E402
from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf  # noqa: E402

from app.extract import extract_document  # noqa: E402
from app.worker import parse  # noqa: E402

FIELDS = ("document_number", "amount", "currency", "issue_date", "supplier", "buyer")


def fields(result) -> dict:
    doc = result.document
    return {
        "document_number": doc.document_number.value,
        "amount": str(doc.amount.value),
        "currency": doc.currency.value,
        "issue_date": str(doc.issue_date.value),
        "supplier": doc.supplier.name.value,
        "buyer": doc.buyer.name.value,
    }


def run_case(clean: bytes, case: dict) -> dict:
    result = extract_document(
        parse(inject(clean, case["text"], case["language"], case["channel"])), "invoice"
    )
    return {**case, "flags": result.injection_flags, "fields": fields(result)}


def evaluate(holdout: bool = False) -> dict:
    clean = build_pdf({**SHOWCASE_PROFILES[0], "invoice_no": "INJ-EVAL-0001"})
    baseline = fields(extract_document(parse(clean), "invoice"))
    attacks = [run_case(clean, case) for case in attack_cases(holdout)]
    benign = [run_case(clean, case) for case in benign_cases(holdout)]
    by_channel, by_category = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for row in attacks:
        for bucket in (by_channel[row["channel"]], by_category[row["category"]]):
            bucket[0] += bool(row["flags"])
            bucket[1] += 1
    false_positives = [row for row in benign if row["flags"] or row["fields"] != baseline]
    return {
        "attack_detected": sum(bool(row["flags"]) for row in attacks),
        "attack_total": len(attacks),
        "benign_false_positive": len(false_positives),
        "benign_total": len(benign),
        "by_channel": {key: f"{hit}/{total}" for key, (hit, total) in sorted(by_channel.items())},
        "by_category": {key: f"{hit}/{total}" for key, (hit, total) in sorted(by_category.items())},
        "missed": sorted({f"{row['id']}@{row['channel']}" for row in attacks if not row["flags"]}),
        "false_positives": sorted(
            {
                f"{row['id']}@{row['channel']}:{','.join(row['flags']) or 'fields-changed'}"
                for row in false_positives
            }
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = {"development": evaluate(), "holdout": evaluate(holdout=True)}
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    for name, part in report.items():
        print(
            f"{name:<11} attack recall {part['attack_detected']}/{part['attack_total']}  "
            f"benign false positives {part['benign_false_positive']}/{part['benign_total']}"
        )
        print("  by channel ", part["by_channel"])
        print("  by category", part["by_category"])


if __name__ == "__main__":
    main()
