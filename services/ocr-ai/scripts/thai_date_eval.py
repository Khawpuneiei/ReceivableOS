"""Measure Thai date handling: Buddhist Era years, Thai month names and Thai digits.

Runs the real /ocr/extract pipeline in-process (no network, no models) on the same
fictional Thai invoice with different date notations, using one fingerprint key so
fingerprints are comparable across notations.

    services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/thai_date_eval.py
"""

from __future__ import annotations

import secrets
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from datagen.thai_dates import FORMATS, thai_invoice  # noqa: E402

from app.config import Settings  # noqa: E402
from app.pipeline import extract_invoice  # noqa: E402

EXPECTED = ("2026-10-01", "2026-11-15")


def main() -> None:
    keys = secrets.token_hex(32), secrets.token_hex(32)
    rows, reference = [], None
    with tempfile.TemporaryDirectory(prefix="ocr-thai-dates-") as folder:
        for index, (name, (issue, due)) in enumerate(FORMATS.items()):
            settings = Settings(*keys, Path(folder) / f"{index}.sqlite", False, False, "", "", True, False)
            try:
                response = extract_invoice(thai_invoice(issue, due), settings, None)
            except HTTPException as exc:
                rows.append((name, issue, f"http_{exc.status_code}", "-", False, False))
                continue
            dates = (str(response.issue_date), str(response.due_date))
            reference = reference or (response.invoice_fingerprint if name == "iso_ce" else None)
            rows.append(
                (
                    name,
                    issue,
                    "200",
                    f"{dates[0]} / {dates[1]}",
                    dates == EXPECTED,
                    response.invoice_fingerprint == reference,
                )
            )
    print(
        "| notation | printed issue date | HTTP | extracted issue / due | correct | same fingerprint as ISO |"
    )
    print("| --- | --- | --- | --- | --- | --- |")
    for row in rows:
        print("| " + " | ".join(str(cell) for cell in row) + " |")
    print(
        f"correct dates {sum(row[4] for row in rows)}/{len(rows)}, "
        f"fingerprint matches ISO {sum(row[5] for row in rows)}/{len(rows)}"
    )


if __name__ == "__main__":
    main()
