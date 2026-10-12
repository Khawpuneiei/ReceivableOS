"""Real staged Paddle image uploads and optional isolated local Qwen cache verification."""

import io
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
from unittest.mock import patch

import httpx
import pymupdf
from fastapi.testclient import TestClient
from PIL import Image

SERVICE = Path(__file__).resolve().parents[1]
REPO = SERVICE.parents[1]
sys.path[:0] = [str(SERVICE), str(REPO)]
from app.main import app  # noqa: E402


def main():
    report, processes = {"data_origin": "synthetic-only", "hosted_live_verified": False}, []
    with tempfile.TemporaryDirectory(prefix="ocr-model-check-") as temporary:
        root = Path(temporary)
        inherited = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
        env = {
            **inherited,
            "PYTHONPATH": str(REPO),
            "LLM_API_KEY": "",
            "OCR_QWEN_ENABLED": "0",
            "FINGERPRINT_HMAC_KEY": secrets.token_hex(32),
            "BANK_TOKEN_HMAC_KEY": secrets.token_hex(32),
            "OCR_RESULT_ACCESS_TOKEN": secrets.token_hex(32),
        }
        try:
            ollama = shutil.which("ollama")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                model_port = sock.getsockname()[1]
            model_url = f"http://127.0.0.1:{model_port}"
            if ollama:
                processes.append(
                    subprocess.Popen(
                        [ollama, "serve"],
                        env={**inherited, "OLLAMA_HOST": model_url},
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                )
                ready = False
                for _ in range(100):
                    try:
                        response = httpx.get(model_url + "/api/tags", timeout=1, trust_env=False)
                        ready = response.status_code == 200
                        if ready:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                if ready:
                    with socket.socket() as sock:
                        sock.bind(("127.0.0.1", 0))
                        api_port = sock.getsockname()[1]
                    api_env = {
                        **env,
                        "OCR_QWEN_ENABLED": "1",
                        "OCR_QWEN_URL": model_url,
                        "OCR_STATE_PATH": str(root / "prewarm.sqlite"),
                    }
                    processes.append(
                        subprocess.Popen(
                            [
                                sys.executable,
                                "-m",
                                "uvicorn",
                                "app.main:app",
                                "--host",
                                "127.0.0.1",
                                "--port",
                                str(api_port),
                            ],
                            cwd=SERVICE,
                            env=api_env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    )
                    api_url = f"http://127.0.0.1:{api_port}"
                    for _ in range(100):
                        try:
                            if httpx.get(api_url + "/health", timeout=1, trust_env=False).status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    print("Verifying real local Qwen demo cache (8 requests)", flush=True)
                    result = subprocess.run(
                        [
                            sys.executable,
                            "scripts/prewarm_llm.py",
                            "--url",
                            api_url,
                            "--env-file",
                            str(root / "no-cloud.env"),
                            "--output",
                            str(root / "warm.json"),
                        ],
                        env=api_env,
                        cwd=SERVICE,
                        capture_output=True,
                        text=True,
                        timeout=600,
                    )
                    report["local_qwen"] = (
                        json.loads((root / "warm.json").read_text())
                        if (root / "warm.json").exists()
                        else {"passed": False, "exit_code": result.returncode}
                    )
                    report["local_qwen"]["verification_server_stopped_after_run"] = True
            report.setdefault("local_qwen", {"passed": False, "reason": "Local runtime unavailable"})
            models = SERVICE / ".cache/paddlex/official_models"
            env.update(
                {
                    "OCR_PADDLE_ENABLED": "1",
                    "OCR_PADDLE_DET_DIR": str(models / "PP-OCRv5_mobile_det"),
                    "OCR_PADDLE_REC_DIR": str(models / "en_PP-OCRv5_mobile_rec"),
                    "OCR_PADDLE_REC_NAME": "en_PP-OCRv5_mobile_rec",
                    "PADDLE_PDX_CACHE_HOME": str(SERVICE / ".cache/paddlex"),
                }
            )
            content = (REPO / "data/invoices/demo/01_happy.pdf").read_bytes()
            with pymupdf.open(stream=content, filetype="pdf") as document:
                png = document[0].get_pixmap(dpi=150).tobytes("png")
            records = []
            for fmt, mime in (("PNG", "image/png"), ("JPEG", "image/jpeg")):
                stream = io.BytesIO()
                Image.open(io.BytesIO(png)).convert("RGB").save(stream, format=fmt, quality=95)
                env["OCR_STATE_PATH"] = str(root / f"{fmt}.sqlite")
                print(f"Verifying real PaddleOCR {fmt} upload", flush=True)
                with patch.dict(os.environ, env), TestClient(app) as client:
                    response = client.post(
                        "/ocr/extract", files={"file": ("sample." + fmt.lower(), stream.getvalue(), mime)}
                    )
                body = response.json()
                expected = {
                    "invoice_no": "SFP-INV-2026-0142",
                    "amount": "749000.00",
                    "currency": "THB",
                    "issue_date": "2026-10-01",
                    "due_date": "2026-11-15",
                }
                matches = {key: body.get(key) == value for key, value in expected.items()}
                matches.update(
                    {
                        "supplier_name": body.get("supplier", {}).get("name") == "Siam Fresh Pack",
                        "buyer_name": body.get("buyer", {}).get("name") == "Mekong Basket Retail PCL",
                    }
                )
                records.append(
                    {
                        "format": fmt,
                        "http_status": response.status_code,
                        "field_matches": matches,
                        "review_required": body.get("review_required"),
                        "validation_flags": body.get("validation_flags"),
                        "passed": response.status_code == 200 and all(matches.values()),
                    }
                )
            report["paddle"] = records
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    target = SERVICE / "docs/CHECKLIST_MODEL_CHECK.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "qwen_cache_passed": report["local_qwen"]["passed"],
                "paddle_passed": sum(r["passed"] for r in report.get("paddle", [])),
                "report": str(target),
            }
        )
    )
    return 0 if report["local_qwen"]["passed"] and all(row["passed"] for row in report["paddle"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
