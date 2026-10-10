"""orchestrator: end-to-end ReceivableOS flow (scope 4.4). Owner: PM.

POST /flow/run: invoice -> ocr-ai -> registry duplicate check -> policy-ai -> (lender quotes) -> agent-wallet.
Stub: the registry is an in-memory set of invoice_fingerprint values and lender quotes are skipped.
"""

import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, UploadFile

OCR_URL = os.getenv("OCR_URL", "http://localhost:8001")
POLICY_URL = os.getenv("POLICY_URL", "http://localhost:8002")
WALLET_URL = os.getenv("WALLET_URL", "http://localhost:8003")
PROFILES = json.loads((Path(__file__).resolve().parents[1] / "samples" / "profiles.json").read_text())

app = FastAPI(title="orchestrator")
_registered: set[str] = set()  # stand-in for the on-chain ReceivableRegistry, keyed by invoice_fingerprint


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "orchestrator"}


@app.post("/flow/run")
async def flow_run(file: UploadFile = File(...), mandate_id: str = Form("mandate-v0.1")) -> dict:
    content = await file.read()
    steps: dict = {"mandate_id": mandate_id}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{OCR_URL}/ocr/extract", files={"file": (file.filename, content)})
        r.raise_for_status()
        invoice = steps["ocr"] = r.json()

        key = invoice["invoice_fingerprint"]
        duplicate = key in _registered
        steps["registry"] = {"invoice_fingerprint": key, "duplicate": duplicate}
        if duplicate:
            steps["outcome"] = "blocked: invoice already registered"
            return steps
        _registered.add(key)

        r = await client.post(f"{POLICY_URL}/policy/decide", json={"invoice": invoice, **PROFILES})
        r.raise_for_status()
        decision = steps["policy"] = r.json()

        r = await client.post(
            f"{WALLET_URL}/wallet/execute",
            json={
                "decision": decision,
                "payee": PROFILES["supplier_profile"].get("wallet_address", "0xSUPPLIER"),
                "amount": decision["limit"],
                "currency": invoice["currency"],
                "invoice_id": invoice["invoice_id"],
            },
        )
        r.raise_for_status()
        steps["wallet"] = r.json()
    steps["outcome"] = steps["wallet"]["status"]
    return steps


@app.post("/flow/repay")
def flow_repay(invoice_id: str = Form(...)) -> dict:
    return {"invoice_id": invoice_id, "status": "stub: settlement not implemented yet"}
