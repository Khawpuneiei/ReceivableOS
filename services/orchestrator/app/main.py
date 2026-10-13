"""orchestrator: end-to-end ReceivableOS flow (scope 4.4). Owner: PM.

POST /flow/run: invoice -> ocr-ai -> duplicate check -> policy-ai -> lender quote -> agent-wallet
(register TX-1, approve TX-2 when the policy says approve, execute TX-4).
POST /flow/repay: buyer paid -> agent-wallet settle (TX-5).

The duplicate check is an in-memory stand-in for the ReceivableRegistry.
The wallet's register is the on-chain check.
Lender quotes are the mock lenders in samples/lenders.json (CLAUDE.md section 1).
"""

import json
import os
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, UploadFile

OCR_URL = os.getenv("OCR_URL", "http://localhost:8001")
POLICY_URL = os.getenv("POLICY_URL", "http://localhost:8002")
WALLET_URL = os.getenv("WALLET_URL", "http://localhost:8003")
WALLET_AGENT_TOKEN = os.getenv("WALLET_AGENT_TOKEN", "")  # register, execute and settle
WALLET_RISK_ORACLE_TOKEN = os.getenv("WALLET_RISK_ORACLE_TOKEN", "")  # approve (TX-2) only
MAX_APR = Decimal(os.getenv("MAX_APR", "0.12"))  # the demo mandate's max_apr; the wallet checks it again
DEFAULT_MANDATE_ID = "mdt_001"  # the demo mandate the wallet activates at startup
SELLER_ID = "SELLER:siam-fresh-pack"  # a payee registry id, never an address
SAMPLES = Path(__file__).resolve().parents[1] / "samples"
PROFILES = json.loads((SAMPLES / "profiles.json").read_text())
LENDERS = json.loads((SAMPLES / "lenders.json").read_text())["quotes"]

app = FastAPI(title="orchestrator")
_registered: set[str] = set()  # stand-in for the on-chain ReceivableRegistry, keyed by invoice_fingerprint
_financed: dict[str, dict] = {}  # invoice_id -> what settle needs, for invoices with an executed draw


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "orchestrator"}


def select_quote(face: Decimal, limit: Decimal) -> dict | None:
    """The mock lender with the highest advance whose APR is within MAX_APR. A tie goes to the lower APR.
    The draw is the quoted advance, but never more than the limit the policy approved."""
    eligible = [q for q in LENDERS if Decimal(q["apr"]) <= MAX_APR]
    if not eligible:
        return None
    best = max(eligible, key=lambda q: (Decimal(q["advance_rate"]), -Decimal(q["apr"])))
    advance = (face * Decimal(best["advance_rate"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "lender_id": best["lender_id"],
        "name": best["name"],
        "apr": best["apr"],
        "amount": min(advance, limit),
    }


async def call_wallet(client: httpx.AsyncClient, path: str, headers: dict, body: dict) -> tuple[int, dict]:
    r = await client.post(f"{WALLET_URL}{path}", headers=headers, json=body)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"detail": r.text}


def wallet_problem(status: int, body: dict) -> str | None:
    """Why the wallet did not carry out the step, or None when it did (or is waiting for an approver)."""
    if status >= 400:
        return f"failed: wallet returned HTTP {status}: {body.get('detail', '')}"
    if body.get("status") in ("blocked", "failed"):
        return f"{body['status']}: {body.get('block_reason') or 'no reason given'}"
    return None


@app.post("/flow/run")
async def flow_run(file: UploadFile = File(...), mandate_id: str = Form(DEFAULT_MANDATE_ID)) -> dict:
    content = await file.read()
    steps: dict = {"mandate_id": mandate_id}
    agent = {"X-Agent-Token": WALLET_AGENT_TOKEN}
    oracle = {"X-Risk-Oracle-Token": WALLET_RISK_ORACLE_TOKEN}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{OCR_URL}/ocr/extract", files={"file": (file.filename, content)})
        r.raise_for_status()
        invoice = steps["ocr"] = r.json()
        invoice_id = invoice["invoice_id"]
        key = invoice["invoice_fingerprint"]

        duplicate = key in _registered
        steps["registry"] = {"invoice_fingerprint": key, "duplicate": duplicate}
        if duplicate:
            steps["outcome"] = "blocked: invoice already registered"
            return steps

        r = await client.post(f"{POLICY_URL}/policy/decide", json={"invoice": invoice, **PROFILES})
        r.raise_for_status()
        decision = steps["policy"] = r.json()
        if decision["decision"] != "approve":
            steps["outcome"] = f"not financed: policy decision is {decision['decision']}"
            return steps

        status, body = await call_wallet(
            client,
            "/wallet/register",
            agent,
            {
                "idempotency_key": f"{invoice_id}:register",
                "invoice_id": invoice_id,
                "invoice_fingerprint": key,
                "doc_hash": invoice["doc_hash"],
                "face_value": invoice["amount"],
                "currency": invoice["currency"],
                "due_date": invoice["due_date"],
                "seller": SELLER_ID,
            },
        )
        steps["register"] = body
        if problem := wallet_problem(status, body):
            steps["outcome"] = problem
            return steps
        _registered.add(key)  # only once the wallet has accepted the receivable

        status, body = await call_wallet(
            client,
            "/wallet/approve",
            oracle,
            {
                "idempotency_key": f"{invoice_id}:approve",
                "decision_id": decision["decision_id"],
                "decision": decision,
                "decision_hash": decision["decision_hash"],
                "invoice_fingerprint": key,
                "limit": decision["limit"],
                "fee_rate": decision["fee_rate"],
                "model_version": decision["model_version"],
                "policy_version": decision["policy_version"],
            },
        )
        steps["approve"] = body
        if problem := wallet_problem(status, body):
            steps["outcome"] = problem
            return steps

        quote = select_quote(Decimal(invoice["amount"]), Decimal(decision["limit"]))
        steps["quote"] = quote
        if quote is None:
            steps["outcome"] = "blocked: no lender quote within the mandate's APR cap"
            return steps

        status, body = await call_wallet(
            client,
            "/wallet/execute",
            agent,
            {
                "idempotency_key": f"{invoice_id}:draw",
                "invoice_id": invoice_id,
                "invoice_fingerprint": key,
                "doc_hash": invoice["doc_hash"],
                "decision": decision,
                "decision_id": decision["decision_id"],
                "decision_hash": decision["decision_hash"],
                "payee": SELLER_ID,
                "amount": str(quote["amount"]),
                "currency": invoice["currency"],
                "apr": quote["apr"],
                "lender_id": quote["lender_id"],
                "mandate_id": mandate_id,
            },
        )
        steps["wallet"] = body
        steps["outcome"] = wallet_problem(status, body) or body["status"]
        if body.get("status") == "executed":
            _financed[invoice_id] = {
                "invoice_fingerprint": key,
                "doc_hash": invoice["doc_hash"],
                "face": invoice["amount"],
            }
    return steps


@app.post("/flow/repay")
async def flow_repay(invoice_id: str = Form(...), amount_paid: str | None = Form(None)) -> dict:
    flow = _financed.get(invoice_id)
    if flow is None:
        return {"invoice_id": invoice_id, "outcome": "not settled: no executed draw for this invoice"}
    async with httpx.AsyncClient(timeout=60) as client:
        status, body = await call_wallet(
            client,
            "/wallet/settle",
            {"X-Agent-Token": WALLET_AGENT_TOKEN},
            {
                "idempotency_key": f"{invoice_id}:settle",
                "invoice_id": invoice_id,
                "invoice_fingerprint": flow["invoice_fingerprint"],
                "doc_hash": flow["doc_hash"],
                "amount_paid": amount_paid or flow["face"],
            },
        )
    return {
        "invoice_id": invoice_id,
        "settle": body,
        "outcome": wallet_problem(status, body) or body["status"],
    }
