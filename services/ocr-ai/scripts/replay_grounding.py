"""Recheck saved Thai OCR evidence against saved model candidates; no live API field writes."""

import hashlib
import json
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]

from experiments.grounding import grounded_candidate  # noqa: E402

from app.ingest import ParsedDocument, Span  # noqa: E402


def main():
    source = SERVICE / "docs/RELIABILITY_EVALUATION.json"
    candidate_source = SERVICE / "docs/RELIABILITY_BASELINE.json"
    report = json.loads(source.read_text())
    assert report["status"] == "complete"
    candidate_report = json.loads(candidate_source.read_text())
    diagnostics = {record["file"]: record for record in report["records"] if "diagnostic_spans" in record}
    results = []
    for sample in candidate_report["qwen_records"]:
        if sample["file"] not in diagnostics:
            continue
        record = diagnostics[sample["file"]]
        assert sample["sha256"] == record["sha256"]
        parsed = ParsedDocument(
            doc_hash="sha256:" + record["sha256"],
            spans=[
                Span(**span, ordinal=index, source="image_ocr")
                for index, span in enumerate(record["diagnostic_spans"])
            ],
            images=[],
            engine=record["engine"],
        )
        grounding = {}
        for field, candidate in sample["candidate_values"].items():
            if field in {"instructions_found", "po_reference"}:
                continue
            target = field.replace("supplier_name", "supplier.name").replace("buyer_name", "buyer.name")
            if sample["document_type"] == "purchase_order" and target == "document_number":
                target = "po_reference"
            grounding[field] = grounded_candidate(parsed, target, candidate, "th-TH")
        results.append(
            {
                "file": sample["file"],
                "repeat": sample["repeat"],
                "grounding": grounding,
                "newly_grounded_fields": [
                    field
                    for field in grounding
                    if record["values"][field] is None and grounding[field]["status"] == "grounded"
                ],
                "wrong_grounded_fields": [
                    field
                    for field in grounding
                    if grounding[field]["status"] == "grounded" and not sample["field_matches"][field]
                ],
            }
        )
    target = SERVICE / "docs/GROUNDING_EXPERIMENT.json"
    target.write_text(
        json.dumps(
            {
                "data_origin": "synthetic-only",
                "prototype_sha256": hashlib.sha256(
                    (SERVICE / "experiments/grounding.py").read_bytes()
                ).hexdigest(),
                "source_evaluation_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "candidate_evaluation_sha256": hashlib.sha256(candidate_source.read_bytes()).hexdigest(),
                "records": results,
                "summary": {
                    "candidate_sets": len(results),
                    "unique_documents": len({item["file"] for item in results}),
                    "newly_grounded_fields": sum(len(item["newly_grounded_fields"]) for item in results),
                    "wrong_grounded_fields": sum(len(item["wrong_grounded_fields"]) for item in results),
                },
                "limitations": [
                    "Replays saved candidates against saved OCR spans; "
                    "scores in diagnostics were rounded to four decimals",
                    "Thai-only followup to the first span-grounding prototype",
                    "No live field changes; abstention does not establish sufficient coverage",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
