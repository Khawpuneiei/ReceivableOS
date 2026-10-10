"""Reproducible synthetic-only evidence and risk-signal evaluation, using isolated state."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from datagen.generate import generate  # noqa: E402

from app.config import Settings  # noqa: E402
from app.pipeline import extract, extract_invoice, verify  # noqa: E402

DATA = SERVICE.parents[1] / "data" / "invoices"
FIELDS = ("document_number", "amount", "currency", "issue_date", "due_date", "supplier_name", "buyer_name")


def settings(path: Path) -> Settings:
    return Settings(
        secrets.token_hex(32),
        secrets.token_hex(32),
        path,
        False,
        False,
        "http://127.0.0.1:11434",
        "qwen3-vl:4b-instruct",
        True,
        False,
    )


def values(doc):
    result = {
        name: str(getattr(doc, name).value) if getattr(doc, name).value is not None else None
        for name in FIELDS
        if name not in {"supplier_name", "buyer_name"}
    }
    result.update(supplier_name=doc.supplier.name.value, buyer_name=doc.buyer.name.value)
    return result


def evaluate(output: Path | None = None):
    rows = []
    signals = []
    pair_rows = []
    with (
        tempfile.TemporaryDirectory(prefix="ocr-evaluation-fixtures-") as fixture_temporary,
        tempfile.TemporaryDirectory(prefix="ocr-evaluation-") as temporary,
    ):
        fixture_root = Path(fixture_temporary)
        labels = generate(fixture_root, font_path=DATA / "fonts" / "NotoSansThai-Regular.ttf")
        root = Path(temporary)
        for index, label in enumerate(labels):
            if label["case"] == "scan":
                continue
            cfg = settings(root / f"field-{index}.sqlite")
            started = time.monotonic()
            result = extract((fixture_root / label["file"]).read_bytes(), label["document_type"], cfg)
            actual = values(result.document)
            matches = {field: actual[field] == label["truth"][field] for field in FIELDS}
            rows.append(
                {
                    "file": label["file"],
                    "language": label["language"],
                    "document_type": label["document_type"],
                    "case": label["case"],
                    "correct": sum(matches.values()),
                    "total": len(FIELDS),
                    "field_matches": matches,
                    "injection_alert": bool(result.injection_flags),
                    "elapsed_seconds": round(time.monotonic() - started, 4),
                }
            )
            if label["document_type"] == "invoice":
                response = verify(
                    (fixture_root / label["file"]).read_bytes(),
                    (fixture_root / f"{label['language']}_po_clean.pdf").read_bytes(),
                    cfg,
                    None,
                )
                pair_rows.append(
                    {
                        "file": label["file"],
                        "status": response.status,
                        "unknown_checks": sum(c.status == "unknown" for c in response.checks),
                        "mismatch_checks": sum(c.status == "mismatch" for c in response.checks),
                    }
                )
        for language in ("en", "th"):

            def invoice(case, language=language):
                return (fixture_root / f"{language}_invoice_{case}.pdf").read_bytes()

            po = (fixture_root / f"{language}_po_clean.pdf").read_bytes()
            for sequence, cases, expected in [
                ("exact_duplicate", ["clean", "clean"], {"duplicate_invoice_hash", "duplicate_fingerprint"}),
                ("semantic_duplicate", ["clean", "duplicate_render"], {"duplicate_fingerprint"}),
                ("near_duplicate", ["clean", "amount_mismatch"], {"near_duplicate", "math_inconsistent"}),
                ("benign_shared_account", ["clean", "shared_account"], {"shared_bank_token"}),
                (
                    "independent_cluster",
                    ["cluster_math", "cluster_currency"],
                    {"shared_bank_token", "suspicious_cluster", "po_currency_mismatch"},
                ),
            ]:
                cfg = settings(root / f"{language}-{sequence}.sqlite")
                for case in cases:
                    response = (
                        verify(invoice(case), po, cfg, None).compatible_invoice
                        if sequence == "independent_cluster"
                        else extract_invoice(invoice(case), cfg, None)
                    )
                found = set(response.fraud_flags)
                baseline = [
                    f
                    for f in response.fraud_details
                    if f.code not in {"shared_bank_token", "suspicious_cluster", "near_duplicate"}
                ]
                from app.fraud import score

                signals.append(
                    {
                        "language": language,
                        "case": sequence,
                        "expected_codes": sorted(expected),
                        "observed_codes": sorted(found),
                        "all_expected_found": expected <= found,
                        "document_duplicate_rules_score": score(baseline),
                        "with_graph_score": response.fraud_score,
                        "evidence_paths_present": all(
                            f.path and f.evidence_refs
                            for f in response.fraud_details
                            if f.code in expected
                            and f.code
                            in {
                                "shared_bank_token",
                                "suspicious_cluster",
                                "near_duplicate",
                                "duplicate_invoice_hash",
                                "duplicate_fingerprint",
                            }
                        ),
                    }
                )
    groups = defaultdict(list)
    for row in rows:
        groups[(row["language"], row["document_type"])].append(row)
    aggregate = []
    for (language, document_type), group in groups.items():
        aggregate.append(
            {
                "language": language,
                "document_type": document_type,
                "documents": len(group),
                "correct": sum(r["correct"] for r in group),
                "total": sum(r["total"] for r in group),
                "fully_correct": sum(r["correct"] == r["total"] for r in group),
            }
        )
    injected = [r for r in rows if r["case"] in {"visible_injection", "hidden_injection"}]
    negatives = [r for r in rows if r["case"] in {"clean", "benign_note"}]
    unchanged = 0
    for row in injected:
        base = next(
            r
            for r in rows
            if r["language"] == row["language"] and r["case"] == "clean" and r["document_type"] == "invoice"
        )
        unchanged += row["field_matches"] == base["field_matches"] and row["correct"] == row["total"]
    latencies = sorted(row["elapsed_seconds"] for row in rows)
    report = {
        "data_origin": "synthetic-only",
        "rules_version": "spatial-rules-v2",
        "code_hashes": {
            str(path.relative_to(SERVICE)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [*sorted((SERVICE / "app").glob("*.py")), Path(__file__)]
        },
        "groups": aggregate,
        "extraction_records": rows,
        "verification_records": pair_rows,
        "risk_sequences": signals,
        "injection": {
            "alerts": sum(r["injection_alert"] for r in injected),
            "injected_documents": len(injected),
            "unchanged_grounded_fields": unchanged,
            "negative_alerts": sum(r["injection_alert"] for r in negatives),
            "negative_documents": len(negatives),
        },
        "latency_seconds": {
            "p50": statistics.median(latencies),
            "p95": latencies[int(0.95 * (len(latencies) - 1))],
        },
        "limitations": [
            "Generated label templates only; no held-out real-world document distribution",
            "Missing expected due date counts as correct explicit null, not full extraction",
            "Graph sequences evaluate planted rule conditions; no real-world accuracy claim",
            "Paddle/Qwen scans are evaluated separately in ENGINE_BENCHMARK.json",
            "Latency is local pipeline extraction with isolated parser startup, excludes HTTP and models",
        ],
    }
    target = output or SERVICE / "docs/EVALUATION.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "groups": aggregate,
                "injection": report["injection"],
                "risk_sequences_passed": sum(r["all_expected_found"] for r in signals),
                "risk_sequences_total": len(signals),
                "report": str(target),
            },
            indent=2,
        )
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    evaluate(parser.parse_args().output)
