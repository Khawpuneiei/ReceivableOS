"""Compare actual parsed SKU/description/quantity/price/total against synthetic labels."""

import argparse
import hashlib
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]

from app.extract import extract_document  # noqa: E402
from app.ingest import ParsedDocument, Span, run_worker  # noqa: E402

KEYS = ("sku", "description", "quantity", "unit_price", "total")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=SERVICE / "docs/RELIABILITY_EVALUATION.json")
    parser.add_argument("--output", type=Path, default=SERVICE / "docs/LINE_EVALUATION.json")
    args = parser.parse_args()
    code_hashes = {
        str(path.relative_to(SERVICE)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [*sorted((SERVICE / "app").glob("*.py")), Path(__file__)]
    }
    corpus = SERVICE.parents[1] / "data/invoices/reliability"
    labels = [json.loads(line) for line in (corpus / "manifest.jsonl").read_text().splitlines()]
    evidence = json.loads(args.evidence.read_text())
    assert evidence["status"] == "complete"
    diagnostics = {item["file"]: item for item in evidence["records"] if "diagnostic_spans" in item}
    models = {"en": "en_PP-OCRv5_mobile_rec", "th": "th_PP-OCRv5_mobile_rec", "zh": "PP-OCRv5_mobile_rec"}
    cache = SERVICE / ".cache/paddlex/official_models"
    os.environ["OCR_PADDLE_DET_DIR"] = str(cache / "PP-OCRv5_mobile_det")
    records = []
    for index, label in enumerate(labels):
        content = (corpus / label["file"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == label["sha256"]
        if label["file"] in diagnostics:
            source = diagnostics[label["file"]]
            parsed = ParsedDocument(
                doc_hash="sha256:" + label["sha256"],
                images=[],
                engine=source["engine"],
                spans=[
                    Span(**span, source="image_ocr", ordinal=i)
                    for i, span in enumerate(source["diagnostic_spans"])
                ],
            )
        else:
            name = models[label["language"]]
            os.environ["OCR_PADDLE_REC_NAME"], os.environ["OCR_PADDLE_REC_DIR"] = name, str(cache / name)
            parsed = run_worker("paddle" if label["format"] == "png" else "parse", content)
        document = extract_document(parsed, label["document_type"]).document
        actual = {line.sku.value: line for line in document.lines if line.sku.value is not None}
        unique = len(actual) == len(document.lines)
        matches = []
        for expected in label["line_truth"]:
            line = actual.get(expected[0]) if unique else None
            fields = {}
            for key, truth in zip(KEYS, expected, strict=True):
                value = getattr(line, key).value if line else None
                fields[key] = value is not None and (
                    str(value) == truth
                    if key in {"sku", "description"}
                    else Decimal(str(value)) == Decimal(truth)
                )
            matches.append(fields)
        records.append(
            {
                "file": label["file"],
                "sha256": label["sha256"],
                "language": label["language"],
                "split": label["split"],
                "layout": label["layout"],
                "expected_lines": len(label["line_truth"]),
                "parsed_lines": len(document.lines),
                "line_field_matches": matches,
                "unexpected_skus": sorted(set(actual) - {line[0] for line in label["line_truth"]}),
                "duplicate_or_missing_skus": not unique,
            }
        )
        print(f"Lines {index + 1}/{len(labels)}: {label['language']} {label['layout']}", flush=True)
    summary = {}
    for language in ("en", "zh", "th"):
        group = [item for item in records if item["language"] == language]
        summary[language] = {
            "documents": len(group),
            "expected_lines": sum(item["expected_lines"] for item in group),
            "correct_lines": sum(all(line.values()) for item in group for line in item["line_field_matches"]),
            "expected_line_fields": sum(item["expected_lines"] * len(KEYS) for item in group),
            "correct_line_fields": sum(
                sum(line.values()) for item in group for line in item["line_field_matches"]
            ),
        }
    args.output.write_text(
        json.dumps(
            {
                "status": "complete",
                "data_origin": "synthetic-only",
                "source_evaluation_sha256": hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
                "code_hashes_at_run_start": code_hashes,
                "summary": summary,
                "records": records,
                "limitations": [
                    "Generated ordered SKU line labels, not independent vendor annotations",
                    "Thai scan spans replay final OCR diagnostics with rounded confidence; "
                    "other scans use fresh staged recognition",
                    "Header-only commercial PNGs have zero annotated lines; "
                    "they do not demonstrate line extraction",
                    "Qwen schema does not extract line items; no Qwen line accuracy is claimed",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
