"""Reproducible synthetic language/layout evaluation; model tests are explicit opt-in."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]

import httpx  # noqa: E402
from experiments.grounding import grounded_candidate  # noqa: E402

from app.config import Settings  # noqa: E402
from app.extract import extract_document  # noqa: E402
from app.ingest import run_worker  # noqa: E402
from app.qwen import SYSTEM_PROMPT, read_candidates  # noqa: E402
from app.validate import validate_document  # noqa: E402

from scripts.evaluation_metrics import FIELDS, matches  # noqa: E402

MODELS = {"en": "en_PP-OCRv5_mobile_rec", "th": "th_PP-OCRv5_mobile_rec", "zh": "PP-OCRv5_mobile_rec"}


def values(document):
    result = {
        field: str(getattr(document, field).value) if getattr(document, field).value is not None else None
        for field in FIELDS
        if not field.endswith("_name")
    }
    result.update(supplier_name=document.supplier.name.value, buyer_name=document.buyer.name.value)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--paddle", action="store_true", help="Run staged OCR without additional Qwen calls")
    parser.add_argument("--corpus", type=Path, default=SERVICE.parents[1] / "data/invoices/reliability")
    parser.add_argument("--output", type=Path, default=SERVICE / "docs/RELIABILITY_EVALUATION.json")
    arguments = parser.parse_args()
    code_hashes = {
        str(path.relative_to(SERVICE)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [
            *sorted((SERVICE / "app").glob("*.py")),
            Path(__file__),
            SERVICE / "experiments/grounding.py",
        ]
    }
    labels = [json.loads(line) for line in (arguments.corpus / "manifest.jsonl").read_text().splitlines()]
    cache = SERVICE / ".cache/paddlex/official_models"
    os.environ["OCR_PADDLE_DET_DIR"] = str(cache / "PP-OCRv5_mobile_det")
    settings = Settings.from_env()
    records, model_records = [], []
    for index, label in enumerate(labels):
        content = (arguments.corpus / label["file"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != label["sha256"]:
            raise ValueError("Corpus input changed after manifest creation")
        started = time.monotonic()
        parsed = run_worker("parse", content)
        base = {
            key: label[key]
            for key in (
                "file",
                "sha256",
                "family",
                "split",
                "layout",
                "language",
                "document_type",
                "format",
                "case",
            )
        }
        if label["format"] == "png" and not (arguments.models or arguments.paddle):
            records.append({**base, "skipped": "LOCAL_ENGINES_NOT_REQUESTED"})
            continue
        if label["format"] == "png":
            name = MODELS[label["language"]]
            os.environ["OCR_PADDLE_REC_NAME"] = name
            os.environ["OCR_PADDLE_REC_DIR"] = str(cache / name)
            parsed = run_worker("paddle", content)
        extraction = extract_document(parsed, label["document_type"])
        document = validate_document(extraction.document)
        observed = values(document)
        field_matches = matches(observed, label["truth"])
        record = {
            **base,
            "engine": parsed.engine,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "values": observed,
            "field_matches": field_matches,
            "full_match": all(field_matches.values()),
            "review_reasons": document.review_reasons,
            "injection_flags": extraction.injection_flags,
            "expected_injection": label["expected_injection"],
            "line_count": len(document.lines),
            "expected_line_count": len(label["line_truth"]),
            "wrong_present_fields": [
                key for key in FIELDS if observed[key] is not None and not field_matches[key]
            ],
        }
        # Only public test-corpus text is captured. No source customer/bank records are used.
        if label["language"] == "th" and label["format"] == "png":
            record["diagnostic_spans"] = [
                {
                    "text": span.text,
                    "confidence": round(span.confidence, 4),
                    "bbox": span.bbox,
                    "page": span.page,
                }
                for span in parsed.spans
                if not span.text.startswith("Bank")
            ]
        records.append(record)
        arguments.output.write_text(
            json.dumps(
                {"status": "running", "records": records, "qwen_records": model_records},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print(
            f"Document {index + 1}/{len(labels)}: {label['language']} {label['layout']} "
            f"{label['document_type']} {sum(field_matches.values())}/7",
            flush=True,
        )
        if not arguments.models or not label["model_sample"]:
            continue
        repeats = 3 if label["layout"] == "stacked" else 1
        for repeat in range(repeats):
            started = time.monotonic()
            candidate = read_candidates(parsed.images, settings)
            proposed = candidate.model_dump() if candidate else {}
            candidate_matches = matches(proposed, label["truth"])
            disagreement = [
                field
                for field in FIELDS
                if proposed.get(field) is not None
                and observed[field] is not None
                and not matches(
                    {field: proposed[field]},
                    {key: label["truth"][key] if key != field else observed[field] for key in FIELDS},
                )[field]
            ]
            grounding = {}
            for field in FIELDS:
                target = field.replace("supplier_name", "supplier.name").replace("buyer_name", "buyer.name")
                if label["document_type"] == "purchase_order" and target == "document_number":
                    target = "po_reference"
                grounding[field] = grounded_candidate(
                    parsed,
                    target,
                    proposed.get(field),
                    document.locale_evidence[0] if len(set(document.locale_evidence)) == 1 else None,
                )
            model_records.append(
                {
                    **base,
                    "repeat": repeat + 1,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "unavailable_or_invalid": candidate is None,
                    "candidate_values": proposed,
                    "field_matches": candidate_matches,
                    "full_match": all(candidate_matches.values()),
                    "false_injection_alert": bool(
                        candidate and candidate.instructions_found and not label["expected_injection"]
                    ),
                    "disagreements": disagreement,
                    "prototype_grounding": grounding,
                    "newly_grounded_fields": [
                        field
                        for field in FIELDS
                        if observed[field] is None and grounding[field]["status"] == "grounded"
                    ],
                    "prototype_wrong_grounded_fields": [
                        field
                        for field in FIELDS
                        if grounding[field]["status"] == "grounded" and not candidate_matches[field]
                    ],
                }
            )
            print(
                f"  Qwen repeat {repeat + 1}: {sum(candidate_matches.values())}/7; "
                f"false-alert={bool(candidate and candidate.instructions_found)}",
                flush=True,
            )
    groups = defaultdict(list)
    for record in records:
        if "skipped" not in record:
            groups[f"{record['language']}/{record['split']}/{record['format']}"].append(record)
    summary = {
        key: {
            "documents": len(group),
            "field_matches": sum(sum(item["field_matches"].values()) for item in group),
            "fields": len(group) * len(FIELDS),
            "full_matches": sum(item["full_match"] for item in group),
            "review_documents": sum(bool(item["review_reasons"]) for item in group),
            "wrong_present_fields": sum(len(item["wrong_present_fields"]) for item in group),
            "injection_alerts": sum(bool(item["injection_flags"]) for item in group),
            "correct_line_counts": sum(item["line_count"] == item["expected_line_count"] for item in group),
        }
        for key, group in groups.items()
    }
    qwen_summary = {}
    for language in ("en", "zh", "th"):
        group = [item for item in model_records if item["language"] == language]
        qwen_summary[language] = {
            "calls": len(group),
            "unique_documents": len({item["file"] for item in group}),
            "field_matches": sum(sum(item["field_matches"].values()) for item in group),
            "fields": len(group) * len(FIELDS),
            "full_matches": sum(item["full_match"] for item in group),
            "false_injection_alerts": sum(item["false_injection_alert"] for item in group),
            "invalid_or_unavailable": sum(item["unavailable_or_invalid"] for item in group),
            "newly_grounded_fields": sum(len(item["newly_grounded_fields"]) for item in group),
            "wrong_grounded_fields": sum(len(item["prototype_wrong_grounded_fields"]) for item in group),
        }
    digest = None
    if arguments.models:
        with httpx.Client(trust_env=False, timeout=10) as client:
            response = client.get(settings.qwen_url + "/api/tags")
            response.raise_for_status()
            digest = next(
                (
                    model["digest"]
                    for model in response.json()["models"]
                    if model["name"] == settings.qwen_model
                ),
                None,
            )
    report = {
        "status": "complete",
        "data_origin": "synthetic-only",
        "corpus_counts": dict(Counter(label["language"] for label in labels)),
        "manifest_sha256": hashlib.sha256((arguments.corpus / "manifest.jsonl").read_bytes()).hexdigest(),
        "models_enabled": arguments.models,
        "paddle_enabled": arguments.models or arguments.paddle,
        "code_hashes_at_run_start": code_hashes,
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "qwen_model": settings.qwen_model,
        "qwen_digest": digest,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "paddle_recognizers": MODELS,
        "summary": summary,
        "qwen_summary": qwen_summary,
        "records": records,
        "qwen_records": model_records,
        "limitations": [
            "All documents and labels are generated; no independently sourced/human-annotated corpus",
            "Holdout uses a separate generated layout family, not unseen real vendor documents",
            "Simplified Chinese exact anchors are experimental; native dates/numerals "
            "and Traditional Chinese are unverified",
            "Qwen tested on 24 stratified scans with extra repeats on six stacked documents; "
            "not all corpus files"
            if arguments.models
            else "No Qwen calls in this run; see RELIABILITY_BASELINE.json",
            "Grounding prototype never writes live fields; safe abstention is not extraction success",
            "Paddle and Qwen run sequentially with uncontrolled host load; latency is observational",
        ],
    }
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"summary": summary, "qwen_summary": qwen_summary}), flush=True)


if __name__ == "__main__":
    main()
