"""One-command offline OCR checks; optional clean clone plus patch and fresh dependency install."""

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

SERVICE = Path(__file__).resolve().parents[1]
REPO = SERVICE.parents[1]


def run(command, cwd, env, *, timeout=300):
    process = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    return {
        "command": [str(part).replace(str(REPO), "<repo>") for part in command],
        "exit_code": process.returncode,
        "passed": process.returncode == 0,
        "output_tail": process.stdout[-3000:].replace(str(REPO), "<repo>"),
        "error_tail": process.stderr[-1000:].replace(str(REPO), "<repo>") if process.returncode else "",
    }


def fresh_check(env):
    with tempfile.TemporaryDirectory(prefix="ocr-fresh-clone-") as temporary:
        root = Path(temporary)
        clone = root / "repo"
        subprocess.run(["git", "clone", "--local", "--quiet", str(REPO), str(clone)], check=True)
        # Overlay the owned OCR patch, excluding ignored env, state and model files.
        changed = (
            subprocess.check_output(
                [
                    "git",
                    "ls-files",
                    "-z",
                    "--modified",
                    "--others",
                    "--exclude-standard",
                    "services/ocr-ai",
                    "data/invoices",
                    "docs/05-ocr-ai.md",
                ],
                cwd=REPO,
            )
            .decode()
            .split("\0")
        )
        for relative in filter(None, changed):
            source, target = REPO / relative, clone / relative
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            elif target.is_file():
                target.unlink()
        service = clone / "services/ocr-ai"
        env = {**env, "PYTHONPATH": str(clone)}
        subprocess.run([sys.executable, "-m", "venv", str(root / "venv")], check=True)
        python = str(root / "venv/bin/python")
        checks = []
        checks.append(run([python, "-m", "pip", "install", "-q", "-r", "requirements-dev.txt"], service, env))
        if not checks[-1]["passed"]:
            return {"passed": False, "checks": checks}
        checks.append(run([python, "-m", "pip", "check"], service, env))
        checks.append(run([python, "scripts/setup_local.py"], service, env))
        checks.append(
            run(
                [
                    python,
                    "datagen/generate.py",
                    "--output",
                    str(root / "fixtures"),
                    "--font",
                    str(clone / "data/invoices/fonts/NotoSansThai-Regular.ttf"),
                ],
                service,
                env,
            )
        )
        checks.append(run([python, "-m", "pytest", "-q"], service, env))
        checks.append(run([python, "-m", "ruff", "check", "."], service, env))
        checks.append(run([python, "-m", "ruff", "format", "--check", "."], service, env))
        server_env = {
            **env,
            "PYTHONPATH": str(clone),
            "OCR_STATE_PATH": str(root / "state.sqlite"),
            "FINGERPRINT_HMAC_KEY": secrets.token_hex(32),
            "BANK_TOKEN_HMAC_KEY": secrets.token_hex(32),
            "OCR_RESULT_ACCESS_TOKEN": secrets.token_hex(32),
        }
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", 8001))
            except OSError:
                checks.append({"command": ["start", "8001"], "passed": False, "reason": "Port 8001 occupied"})
                return {"passed": False, "checks": checks}
        process = subprocess.Popen(
            [python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001"],
            cwd=service,
            env=server_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with httpx.Client(timeout=30, trust_env=False) as client:
                for _ in range(100):
                    try:
                        if client.get("http://127.0.0.1:8001/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                content = (root / "fixtures/demo/01_happy.pdf").read_bytes()
                result = client.post(
                    "http://127.0.0.1:8001/ocr/extract", files={"file": ("i.pdf", content, "application/pdf")}
                )
                passed = result.status_code == 200 and result.json().get("amount") == "749000.00"
                fetched = client.get(
                    "http://127.0.0.1:8001/ocr/invoices/" + result.json().get("invoice_id", "missing"),
                    headers={"X-OCR-Result-Token": server_env["OCR_RESULT_ACCESS_TOKEN"]},
                )
                checks.append(
                    {
                        "command": ["HTTP", "8001", "extract", "GET"],
                        "passed": passed and fetched.status_code == 200 and fetched.json() == result.json(),
                    }
                )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        # Temporary clone paths are meaningless after cleanup; no secrets are recorded.
        for check in checks:
            check["command"] = [part.replace(str(root), "<temporary>") for part in check["command"]]
            for field in ("output_tail", "error_tail"):
                if field in check:
                    check[field] = check[field].replace(str(root), "<temporary>")
        return {
            "passed": all(c["passed"] for c in checks),
            "checks": checks,
            "snapshot": "local git clone plus current OCR patch",
            "cloud_key": False,
            "paddle_installed": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument(
        "--strict", action="store_true", help="Fail on outstanding downstream Policy controls"
    )
    args = parser.parse_args()
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    env.update(
        {"PYTHONPATH": str(REPO), "OCR_PADDLE_ENABLED": "0", "OCR_QWEN_ENABLED": "0", "LLM_API_KEY": ""}
    )
    commands = [
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "scripts/eval.py", "--output", "docs/CHECKLIST_EVALUATION.json"],
        [sys.executable, "scripts/case_loop.py"],
        [sys.executable, "scripts/demo_order.py"],
        [sys.executable, "scripts/demo_loop.py", "--skip-fraud-eval"],
    ]
    results = []
    for command in commands:
        print("Checking " + " ".join(command[1:]), flush=True)
        results.append(run(command, SERVICE, env))
    report = {
        "checks": results,
        "ocr_checks_passed": all(check["passed"] for check in results),
        "release_scope": (
            "Offline OCR checks plus mock-owner Policy guard gate; "
            "excludes PM review and live hosted inference"
        ),
        "unverified": [
            "Live hosted provider/model inference",
            "Global vendor holdout >=90%",
            "Authoritative issuer/bank/signature/settlement verification",
            "PM-owned complete Wallet lifecycle and successful drawdown",
        ],
    }
    if args.fresh:
        print("Checking clean clone with fresh virtual environment", flush=True)
        report["fresh_clone"] = fresh_check(env)
        report["ocr_checks_passed"] &= report["fresh_clone"]["passed"]
    demo = json.loads((SERVICE / "docs/DEMO_LOOP_RESULTS.json").read_text())
    report["policy_control_violations"] = demo["policy_control_violations"]
    report["release_ready"] = report["ocr_checks_passed"] and not report["policy_control_violations"]
    target = SERVICE / "docs/RELEASE_CHECK.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "ocr_checks_passed": report["ocr_checks_passed"],
                "release_ready": report["release_ready"],
                "policy_control_violations": report["policy_control_violations"],
                "report": str(target),
            }
        )
    )
    return 0 if report["ocr_checks_passed"] and (not args.strict or report["release_ready"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
