"""Run the repository's existing mock demo with isolated OCR state and free ports."""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

SERVICE = Path(__file__).resolve().parents[1]
REPO = SERVICE.parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    processes = []
    with tempfile.TemporaryDirectory(prefix="ocr-integration-") as temporary:
        env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
        env.update(
            PYTHONPATH=str(REPO),
            FINGERPRINT_HMAC_KEY=secrets.token_hex(32),
            BANK_TOKEN_HMAC_KEY=secrets.token_hex(32),
            OCR_STATE_PATH=str(Path(temporary) / "observations.sqlite"),
            OCR_PADDLE_ENABLED="0",
            OCR_QWEN_ENABLED="0",
            CHAIN_MODE="mock",
        )
        ports = {name: free_port() for name in ("ocr-ai", "policy-ai", "agent-wallet", "orchestrator")}
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
        try:
            with httpx.Client(trust_env=False, timeout=5) as client:
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
                    deadline = time.monotonic() + 15
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError(f"Local {name} could not start")
                        try:
                            response = client.get(f"http://127.0.0.1:{port}/health")
                            response.raise_for_status()
                            break
                        except httpx.HTTPError:
                            if time.monotonic() >= deadline:
                                raise RuntimeError(f"Local {name} startup timed out") from None
                            time.sleep(0.1)
                invoice = REPO / "data/invoices/demo/01_happy.pdf"
                # Use the actual checked-in demo command, unchanged.
                demo = subprocess.run(
                    [
                        sys.executable,
                        str(REPO / "services/orchestrator/run_demo.py"),
                        str(invoice),
                    ],
                    env=env,
                    cwd=REPO,
                    capture_output=True,
                    text=True,
                    timeout=90,
                    check=True,
                )
                payload = json.loads(demo.stdout)
                assert payload["outcome"] == "pending_approval"
                duplicate = client.post(
                    env["ORCHESTRATOR_URL"] + "/flow/run",
                    files={
                        "file": (invoice.name, invoice.read_bytes(), "application/pdf"),
                    },
                )
                duplicate.raise_for_status()
                assert duplicate.json()["registry"]["duplicate"] is True
                assert duplicate.json()["outcome"] == "blocked: invoice already registered"
                report = {
                    "status": "complete",
                    "chain_mode": "mock",
                    "llm_network_used": False,
                    "source": "unchanged services/orchestrator/run_demo.py against four local HTTP services",
                    "happy_outcome": payload["outcome"],
                    "duplicate_outcome": duplicate.json()["outcome"],
                    "ocr_model_version": payload["ocr"]["model_version"],
                    "handoff_version": payload["ocr"]["handoff"]["schema_version"],
                    "graph_version": payload["ocr"]["fraud_graph"]["schema_version"],
                    "limitations": [
                        "Policy and wallet in this checkout are stubs; "
                        "no guard, signature or chain transaction tested",
                        "Orchestrator uses an in-memory registry "
                        "and does not consume OCR pair/handoff fields",
                        "Happy and duplicate transport compatibility only; "
                        "no downstream security acceptance claim",
                    ],
                }
                (SERVICE / "docs/ARCHITECTURE_INTEGRATION.json").write_text(
                    json.dumps(report, indent=2) + "\n"
                )
                print(json.dumps(report))
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
