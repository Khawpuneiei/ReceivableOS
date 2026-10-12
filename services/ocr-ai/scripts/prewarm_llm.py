"""Warm the running single-worker cache without creating duplicate invoice observations."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

SERVICE = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--data", type=Path, default=SERVICE.parents[1] / "data/invoices/demo")
    parser.add_argument("--env-file", type=Path, default=SERVICE / ".env.local")
    parser.add_argument("--output", type=Path, default=SERVICE / "docs/LLM_PREWARM.json")
    args = parser.parse_args()
    address = urlparse(args.url)
    if address.hostname not in {"127.0.0.1", "localhost"} or address.scheme != "http" or address.username:
        raise SystemExit("Prewarm runner accepts a loopback service URL only")
    load_dotenv(args.env_file, override=False)
    token = os.getenv("OCR_RESULT_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Configure OCR_RESULT_ACCESS_TOKEN in the private env file first")
    records = []
    with httpx.Client(timeout=180, trust_env=False) as client:
        for round_no in (1, 2):
            for file in sorted(args.data.glob("0[1-4]_*.pdf")):
                response = client.post(
                    args.url.rstrip("/") + "/ocr/llm/prewarm",
                    headers={"X-OCR-Result-Token": token},
                    files={"file": (file.name, file.read_bytes(), "application/pdf")},
                )
                response.raise_for_status()
                records.append({"round": round_no, "file": file.name, **response.json()})
    passed = len(records) == 8 and all(
        row["checks"]
        and all(
            check["valid_schema"] and (row["round"] != 2 or check["cache"] == "hit")
            for check in row["checks"]
        )
        for row in records
    )
    report = {
        "passed": passed,
        "records": records,
        "hosted_live_verified": any(
            check["provider"] == "hosted" and check["valid_schema"]
            for row in records
            for check in row["checks"]
        ),
        "limitations": [
            "RAM cache expires after 15 minutes and is lost on restart; use one worker for this demo",
            "Prewarm validates schema, not field accuracy or authenticity",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": passed, "requests": len(records), "report": str(args.output)}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
