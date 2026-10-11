"""Run a synthetic OCR -> pair check -> fraud -> Policy demo with isolated services."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import httpx

SERVICE = Path(__file__).resolve().parents[1]
REPO = SERVICE.parents[1]
sys.path.insert(0, str(SERVICE))

from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf  # noqa: E402
from scripts.smoke_integration import assess_policy_controls  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_demo(invoice: Path | None, env: dict[str, str]) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "services/orchestrator/run_demo.py"),
            *([str(invoice)] if invoice else []),
        ],
        env=env,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return json.loads(result.stdout)


def upload(path: Path) -> tuple[str, bytes, str]:
    return path.name, path.read_bytes(), "application/pdf"


def graph_summary(graph: dict | None) -> dict:
    graph = graph or {}
    return {
        "schema_version": graph.get("schema_version"),
        "node_count": len(graph.get("nodes") or []),
        "edge_count": len(graph.get("edges") or []),
        "relations": dict(Counter(edge["relation"] for edge in graph.get("edges") or [])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SERVICE / "docs/DEMO_LOOP_RESULTS.json")
    parser.add_argument(
        "--skip-fraud-eval", action="store_true", help="Skip the 10-sequence synthetic graph evaluation"
    )
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when Policy hard guards fail")
    args = parser.parse_args()

    processes: list[subprocess.Popen] = []
    checks: list[dict] = []
    policy_controls: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="receivableos-ocr-demo-") as temporary:
        root = Path(temporary)
        fixture_dir = root / "fixtures"
        fixture_dir.mkdir()
        profile = dict(SHOWCASE_PROFILES[0])
        clean_invoice = fixture_dir / "invoice-clean.pdf"
        clean_po = fixture_dir / "purchase-order-clean.pdf"
        injected_invoice = fixture_dir / "invoice-injected.pdf"
        mismatch_invoice = fixture_dir / "invoice-amount-mismatch.pdf"
        clean_invoice.write_bytes(build_pdf(profile))
        clean_po.write_bytes(build_pdf(profile, kind="purchase_order"))
        injected_profile = dict(profile, invoice_no="SFP-INV-2026-0143")
        injected_invoice.write_bytes(build_pdf(injected_profile, visible_injection=True))
        mismatch_profile = dict(profile, invoice_no="SFP-INV-2026-0144", total="849000.00")
        mismatch_invoice.write_bytes(build_pdf(mismatch_profile))

        inherited = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
        env = {
            **inherited,
            "PYTHONPATH": str(REPO),
            "FINGERPRINT_HMAC_KEY": secrets.token_hex(32),
            "BANK_TOKEN_HMAC_KEY": secrets.token_hex(32),
            "OCR_STATE_PATH": str(root / "observations.sqlite"),
            "OCR_PADDLE_ENABLED": "0",
            "OCR_QWEN_ENABLED": "0",
            "OCR_DEVELOPMENT_MODE": "1",
            "CHAIN_MODE": "mock",
        }
        names = ("ocr-ai", "policy-ai", "agent-wallet", "orchestrator")
        ports = {name: free_port() for name in names}
        pair_ocr_port = free_port()
        env.update(
            {
                key: f"http://127.0.0.1:{ports[name]}"
                for key, name in (
                    ("OCR_URL", "ocr-ai"),
                    ("POLICY_URL", "policy-ai"),
                    ("WALLET_URL", "agent-wallet"),
                    ("ORCHESTRATOR_URL", "orchestrator"),
                )
            }
        )
        report: dict = {
            "schema_version": "ocr-demo-loop-v1",
            "data_origin": "synthetic_only",
            "execution": {
                "chain_mode": "mock",
                "ocr_paddle_enabled": False,
                "ocr_qwen_enabled": False,
                "services_bound_to": "127.0.0.1",
                "external_model_or_llm_calls": False,
                "fixture_lifecycle": "temporary_directory_removed_after_run",
            },
            "documents": {
                "invoice_types_created": ["commercial_invoice", "purchase_order"],
                "variants": ["clean", "visible_prompt_injection", "amount_mismatch", "same_invoice_repeat"],
                "generator": "services/ocr-ai/datagen/showcase_invoices.py",
            },
            "request_contracts": [
                {
                    "step": "end_to_end_invoice_flow",
                    "method": "POST",
                    "path": "/flow/run",
                    "content_type": "multipart/form-data",
                    "fields": {"file": "invoice PDF", "mandate_id": "optional form field"},
                },
                {
                    "step": "invoice_purchase_order_verification",
                    "method": "POST",
                    "path": "/ocr/verify",
                    "content_type": "multipart/form-data",
                    "fields": {
                        "invoice_file": "invoice PDF",
                        "po_file": "purchase-order PDF",
                    },
                },
                {
                    "step": "policy_decision",
                    "method": "POST",
                    "path": "/policy/decide",
                    "content_type": "application/json",
                    "body_shape": {
                        "invoice": "shared.schemas.ExtractedInvoice",
                        "supplier_profile": "object",
                        "buyer_profile": "object",
                    },
                    "note": (
                        "The current shared request has no typed Invoice/PO handoff or fraud-graph field."
                    ),
                },
                {
                    "step": "result_artifact",
                    "path": "services/ocr-ai/docs/DEMO_LOOP_RESULTS.json",
                    "content_type": "application/json",
                },
            ],
        }
        try:
            with httpx.Client(trust_env=False, timeout=10) as client:
                for name, port in ports.items():
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "app.main:app",
                            "--app-dir",
                            str(REPO / "services" / name),
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(port),
                        ],
                        cwd=REPO,
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    processes.append(process)
                    deadline = time.monotonic() + 20
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError(f"Local {name} could not start")
                        try:
                            client.get(f"http://127.0.0.1:{port}/health").raise_for_status()
                            break
                        except httpx.HTTPError:
                            if time.monotonic() >= deadline:
                                raise RuntimeError(f"Local {name} startup timed out") from None
                            time.sleep(0.1)

                # Pair checks use their own observation history so the preceding
                # end-to-end flow does not correctly make the same invoice look duplicate.
                pair_env = {**env, "OCR_STATE_PATH": str(root / "pair-observations.sqlite")}
                pair_process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.main:app",
                        "--app-dir",
                        str(REPO / "services/ocr-ai"),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(pair_ocr_port),
                    ],
                    cwd=REPO,
                    env=pair_env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes.append(pair_process)
                deadline = time.monotonic() + 20
                while True:
                    if pair_process.poll() is not None:
                        raise RuntimeError("Local isolated pair-check OCR service could not start")
                    try:
                        client.get(f"http://127.0.0.1:{pair_ocr_port}/health").raise_for_status()
                        break
                    except httpx.HTTPError:
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                "Local isolated pair-check OCR service startup timed out"
                            ) from None
                        time.sleep(0.1)
                pair_ocr_url = f"http://127.0.0.1:{pair_ocr_port}"

                profiles_path = REPO / "services/orchestrator/samples/profiles.json"
                profiles = json.loads(profiles_path.read_text())
                happy = run_demo(clean_invoice, env)
                actual = happy["ocr"]
                expected = {
                    "invoice_no": profile["invoice_no"],
                    "amount": profile["total"],
                    "currency": profile["currency"],
                    "due_date": profile["due_date"],
                    "supplier": profile["supplier"],
                    "buyer": profile["buyer"],
                }
                observed = {
                    "invoice_no": actual["invoice_no"],
                    "amount": actual["amount"],
                    "currency": actual["currency"],
                    "due_date": actual["due_date"],
                    "supplier": actual["supplier"]["name"],
                    "buyer": actual["buyer"]["name"],
                }
                field_matches = {field: observed[field] == value for field, value in expected.items()}
                evidence = actual.get("document_evidence") or {}
                grounded_fields = (
                    "document_number",
                    "amount",
                    "currency",
                    "due_date",
                )
                grounding = {
                    field: (evidence.get(field) or {}).get("status") == "present"
                    and bool((evidence.get(field) or {}).get("evidence_refs"))
                    for field in grounded_fields
                }
                checks.extend(
                    [
                        {
                            "name": "clean_invoice_fields_match_mock_truth",
                            "passed": all(field_matches.values()),
                            "details": field_matches,
                        },
                        {
                            "name": "critical_fields_have_evidence_refs",
                            "passed": all(grounding.values()),
                            "details": grounding,
                        },
                    ]
                )
                policy_controls.append(assess_policy_controls(actual, happy["policy"]))

                duplicate = client.post(
                    env["ORCHESTRATOR_URL"] + "/flow/run",
                    files={"file": upload(clean_invoice)},
                )
                duplicate.raise_for_status()
                duplicate_payload = duplicate.json()
                duplicate_codes = duplicate_payload["ocr"].get("fraud_flags", [])
                duplicate_blocked = (
                    duplicate_payload.get("registry", {}).get("duplicate") is True
                    and duplicate_payload.get("outcome") == "blocked: invoice already registered"
                )
                checks.append(
                    {
                        "name": "same_invoice_repeat_blocked_by_registry",
                        "passed": duplicate_blocked,
                        "details": {"fraud_codes": duplicate_codes},
                    }
                )

                clean_pair_response = client.post(
                    pair_ocr_url + "/ocr/verify",
                    files={"invoice_file": upload(clean_invoice), "po_file": upload(clean_po)},
                )
                clean_pair_response.raise_for_status()
                clean_pair = clean_pair_response.json()
                clean_pair_ok = clean_pair["status"] == "matched"
                checks.append({"name": "clean_invoice_po_pair_matches", "passed": clean_pair_ok})

                mismatch_response = client.post(
                    pair_ocr_url + "/ocr/verify",
                    files={"invoice_file": upload(mismatch_invoice), "po_file": upload(clean_po)},
                )
                mismatch_response.raise_for_status()
                mismatch = mismatch_response.json()
                mismatch_invoice_payload = mismatch.get("compatible_invoice") or {}
                mismatch_handoff = mismatch.get("handoff") or {}
                mismatch_codes = sorted(
                    {finding["code"] for finding in mismatch.get("fraud_details") or []}
                    | set(mismatch_handoff.get("fraud_codes") or [])
                )
                mismatch_fields = sorted(
                    check["field"] for check in mismatch.get("checks") or [] if check["status"] == "mismatch"
                )
                mismatch_score = float(
                    mismatch_invoice_payload.get("fraud_score", mismatch_handoff.get("fraud_score", 0.0))
                )
                mismatch_ok = mismatch["status"] == "mismatch" and mismatch_score >= 0.30
                checks.append(
                    {
                        "name": "amount_mismatch_creates_fraud_handoff",
                        "passed": mismatch_ok,
                        "details": {
                            "pair_status": mismatch["status"],
                            "mismatch_fields": mismatch_fields,
                            "fraud_codes": mismatch_codes,
                            "fraud_score": mismatch_score,
                            "review_required": mismatch_handoff.get("review_required"),
                        },
                    }
                )
                if mismatch_invoice_payload:
                    policy_response = client.post(
                        env["POLICY_URL"] + "/policy/decide",
                        json={"invoice": mismatch_invoice_payload, **profiles},
                    )
                    policy_response.raise_for_status()
                    policy_controls.append(
                        assess_policy_controls(mismatch_invoice_payload, policy_response.json())
                    )
                else:
                    checks.append({"name": "mismatch_projection_available_to_policy", "passed": False})

                injected = run_demo(injected_invoice, env)
                injected_ocr = injected["ocr"]
                injection_flags = sorted(set(injected_ocr.get("injection_flags") or []))
                injection_ok = bool(injection_flags) and bool(injected_ocr.get("review_required"))
                checks.append(
                    {
                        "name": "visible_injection_detected_and_review_required_by_ocr",
                        "passed": injection_ok,
                        "details": {"injection_flags": injection_flags},
                    }
                )
                policy_controls.append(assess_policy_controls(injected_ocr, injected["policy"]))

                # Exercise the PM's unchanged default file with an independent registry.
                # The legacy text fixture must reach Policy review, never be fabricated as a PDF.
                legacy_port = free_port()
                legacy_env = {**env, "ORCHESTRATOR_URL": f"http://127.0.0.1:{legacy_port}"}
                legacy_process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.main:app",
                        "--app-dir",
                        str(REPO / "services/orchestrator"),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(legacy_port),
                    ],
                    cwd=REPO,
                    env=legacy_env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes.append(legacy_process)
                deadline = time.monotonic() + 20
                while True:
                    try:
                        client.get(legacy_env["ORCHESTRATOR_URL"] + "/health").raise_for_status()
                        break
                    except httpx.HTTPError:
                        if legacy_process.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("Legacy demo orchestrator could not start") from None
                        time.sleep(0.1)
                legacy = run_demo(None, legacy_env)
                legacy_ocr = legacy["ocr"]
                legacy_ok = (
                    legacy_ocr.get("extractor") == "development_legacy_text"
                    and legacy_ocr.get("amount") == "749000.00"
                    and legacy_ocr.get("review_required") is True
                    and legacy["policy"].get("decision") == "review"
                )
                checks.append(
                    {"name": "unchanged_run_demo_default_text_reaches_policy_review", "passed": legacy_ok}
                )
                policy_controls.append(assess_policy_controls(legacy_ocr, legacy["policy"]))
                report["legacy_default_demo"] = {
                    "file": "data/invoices/demo_invoice.txt",
                    "passed": legacy_ok,
                    "policy_decision": legacy["policy"].get("decision"),
                    "flow_outcome": legacy.get("outcome"),
                    "development_mode": True,
                }

                report["demo_runs"] = {
                    "clean_invoice": {
                        "extracted_values": observed,
                        "ground_truth_matches": field_matches,
                        "grounded_critical_fields": grounding,
                        "ocr_model_version": actual.get("model_version"),
                        "fraud_score": actual.get("fraud_score"),
                        "fraud_codes": actual.get("fraud_flags", []),
                        "graph": graph_summary(actual.get("fraud_graph")),
                        "policy_decision": happy["policy"].get("decision"),
                        "policy_version": happy["policy"].get("policy_version"),
                        "wallet_status": (happy.get("wallet") or {}).get("status"),
                        "flow_outcome": happy.get("outcome"),
                    },
                    "repeat_invoice": {
                        "registry_duplicate": duplicate_payload.get("registry", {}).get("duplicate"),
                        "flow_outcome": duplicate_payload.get("outcome"),
                        "fraud_codes": duplicate_codes,
                        "graph": graph_summary(duplicate_payload["ocr"].get("fraud_graph")),
                    },
                    "clean_invoice_po": {
                        "status": clean_pair.get("status"),
                        "check_counts": dict(
                            Counter(check["status"] for check in clean_pair.get("checks", []))
                        ),
                        "fraud_codes": sorted((clean_pair.get("handoff") or {}).get("fraud_codes", [])),
                        "graph": graph_summary(clean_pair.get("fraud_graph")),
                    },
                    "amount_mismatch_invoice_po": {
                        "status": mismatch.get("status"),
                        "mismatch_fields": mismatch_fields,
                        "fraud_score": mismatch_score,
                        "fraud_codes": mismatch_codes,
                        "handoff_review_required": mismatch_handoff.get("review_required"),
                        "graph": graph_summary(mismatch.get("fraud_graph")),
                    },
                    "injection_invoice": {
                        "injection_flags": injection_flags,
                        "review_required": injected_ocr.get("review_required"),
                        "policy_decision": injected["policy"].get("decision"),
                        "wallet_status": (injected.get("wallet") or {}).get("status"),
                        "flow_outcome": injected.get("outcome"),
                    },
                }

                if not args.skip_fraud_eval:
                    eval_path = root / "fraud-evaluation.json"
                    subprocess.run(
                        [sys.executable, str(SERVICE / "scripts/eval.py"), "--output", str(eval_path)],
                        cwd=REPO,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=180,
                        check=True,
                    )
                    eval_report = json.loads(eval_path.read_text())
                    sequences = eval_report["risk_sequences"]
                    report["synthetic_fraud_evaluation"] = {
                        "risk_sequences_passed": sum(row["all_expected_found"] for row in sequences),
                        "risk_sequences_total": len(sequences),
                        "sequence_results": [
                            {
                                "language": row["language"],
                                "case": row["case"],
                                "expected_codes": row["expected_codes"],
                                "observed_codes": row["observed_codes"],
                                "all_expected_found": row["all_expected_found"],
                                "evidence_paths_present": row["evidence_paths_present"],
                            }
                            for row in sequences
                        ],
                        "injection": eval_report["injection"],
                        "groups": eval_report["groups"],
                    }
                    checks.append(
                        {
                            "name": "all_synthetic_fraud_graph_sequences_detected",
                            "passed": all(row["all_expected_found"] for row in sequences),
                            "details": {
                                "passed": sum(row["all_expected_found"] for row in sequences),
                                "total": len(sequences),
                            },
                        }
                    )

                report["checks"] = checks
                report["policy_controls"] = policy_controls
                report["policy_control_violations"] = sum(
                    item["status"] == "control_violation" for item in policy_controls
                )
                core_passed = all(item["passed"] for item in checks)
                if core_passed and not report["policy_control_violations"]:
                    report["status"] = "passed"
                elif core_passed:
                    report["status"] = "completed_with_policy_gaps"
                else:
                    report["status"] = "failed"
                report["limitations"] = [
                    (
                        "All generated documents and risk sequences are synthetic; this is not a "
                        "real-world fraud precision/recall estimate."
                    ),
                    (
                        "The current Policy service enforces the injection-review and fraud-score "
                        "guards exercised here; Policy source is owned outside OCR."
                    ),
                    (
                        "Wallet remains a demo stub; this loop does not verify wallet guard execution "
                        "or submit a real chain transaction."
                    ),
                    (
                        "The orchestrator registry is process-local memory; this repeat test is not "
                        "durable registry validation."
                    ),
                    (
                        "OCR pair verification supports Invoice and Purchase Order only; other evidence "
                        "types are cataloged as future scope."
                    ),
                    (
                        "Fraud score is uncalibrated rule aggregation and exercises only the "
                        "documented Policy threshold here."
                    ),
                ]
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if "100-200-3001" in serialized or "1002003001" in serialized:
        raise RuntimeError("Refusing to write a demo report containing a raw bank account")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(args.output),
                "checks": checks,
                "policy_control_violations": report.get("policy_control_violations"),
            },
            ensure_ascii=False,
        )
    )
    return 1 if args.strict and report["status"] != "passed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
