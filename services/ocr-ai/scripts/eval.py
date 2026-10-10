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
from datagen.security_corpus import corpus  # noqa: E402

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
    defence_rows = []
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
                        "label_positive": sequence != "benign_shared_account",
                        "predicted_positive": response.fraud_score >= 0.30,
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
            response = extract_invoice(invoice("clean"), settings(root / f"{language}-negative.sqlite"), None)
            signals.append(
                {
                    "language": language,
                    "case": "clean_negative",
                    "expected_codes": [],
                    "observed_codes": response.fraud_flags,
                    "all_expected_found": not response.fraud_flags,
                    "label_positive": False,
                    "predicted_positive": response.fraud_score >= 0.30,
                    "document_duplicate_rules_score": response.fraud_score,
                    "with_graph_score": response.fraud_score,
                    "evidence_paths_present": True,
                }
            )
        for index, item in enumerate(corpus()):
            cfg = settings(root / f"defence-{index}.sqlite")
            baseline = extract(item["clean"], "invoice", cfg)
            attacked = extract(item["content"], "invoice", cfg)
            before, after = values(baseline.document), values(attacked.document)
            defence_rows.append(
                {
                    "name": item["name"],
                    "mechanism": item["mechanism"],
                    "label_attack": item["attack"],
                    "alert": bool(attacked.injection_flags),
                    "flags": attacked.injection_flags,
                    "values_unchanged": before == after,
                    "correct_fields": sum(before[field] == after[field] for field in FIELDS),
                    "total_fields": len(FIELDS),
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
    attacks = [r for r in defence_rows if r["label_attack"]]
    hard_negatives = [r for r in defence_rows if not r["label_attack"]]
    tp = sum(r["label_positive"] and r["predicted_positive"] for r in signals)
    fp = sum(not r["label_positive"] and r["predicted_positive"] for r in signals)
    fn = sum(r["label_positive"] and not r["predicted_positive"] for r in signals)
    tn = sum(not r["label_positive"] and not r["predicted_positive"] for r in signals)
    clean = [r for r in rows if r["case"] == "clean"]
    metrics = {
        "clean_pdf_fields": {
            "correct": sum(r["correct"] for r in clean),
            "total": sum(r["total"] for r in clean),
        },
        "injection_catch_rate": sum(r["alert"] for r in attacks) / len(attacks),
        "attack_success_rate": sum(not r["values_unchanged"] for r in attacks) / len(attacks),
        "hard_negative_false_positive_rate": sum(r["alert"] for r in hard_negatives) / len(hard_negatives),
        "fraud": {
            "threshold": 0.30,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else 0,
            "recall": tp / (tp + fn) if tp + fn else 0,
        },
    }
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
        "checklist_metrics": metrics,
        "defence_records": defence_rows,
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
    print("| Metric (synthetic, rules-only) | Result | Target |")
    print("| --- | --- | --- |")
    print(
        f"| Clean PDF field accuracy (7 fields, {len(clean)} PDFs) | "
        f"{metrics['clean_pdf_fields']['correct'] / metrics['clean_pdf_fields']['total']:.1%} "
        "| >=90%, aim98% |"
    )
    print(f"| Injection catch ({len(attacks)} PDFs) | {metrics['injection_catch_rate']:.1%} | >=95% |")
    print(f"| Attack success (changed 7 fields) | {metrics['attack_success_rate']:.1%} | 0% |")
    print(
        f"| Hard-negative false positives ({len(hard_negatives)} PDFs) | "
        f"{metrics['hard_negative_false_positive_rate']:.1%} | <=5% |"
    )
    print(
        f"| Planted fraud precision / recall ({len(signals)} sequences) | "
        f"{metrics['fraud']['precision']:.1%} / {metrics['fraud']['recall']:.1%} | >=90% / >=90% |"
    )
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
