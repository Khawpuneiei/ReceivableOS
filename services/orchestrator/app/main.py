"""orchestrator: end-to-end ReceivableOS flow (scope 4.4). Owner: PM.

POST /flow/run: invoice -> ocr-ai -> agent-wallet register (TX-1, the ReceivableRegistry duplicate check)
              -> policy-ai -> lender quote -> agent-wallet approve (TX-2) -> agent-wallet execute (TX-4).
POST /flow/repay: "buyer paid" -> agent-wallet settle (TX-5).

A decision that is not `approve` stops after policy-ai: the wallet is never asked to approve or pay it.
The wallet's tokens come from env: the agent token signs register, execute and settle; the risk oracle's token
signs approve. Lender quotes are the mock market in data/agent/lender_quotes.json.
"""

import json
import os
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from shared.money import fee_rate_30d_to_apr

OCR_URL = os.getenv("OCR_URL", "http://localhost:8001")
POLICY_URL = os.getenv("POLICY_URL", "http://localhost:8002")
WALLET_URL = os.getenv("WALLET_URL", "http://localhost:8003")
WALLET_AGENT_TOKEN = os.getenv("WALLET_AGENT_TOKEN", "")  # X-Agent-Token: register, execute, settle
WALLET_RISK_ORACLE_TOKEN = os.getenv("WALLET_RISK_ORACLE_TOKEN", "")  # X-Risk-Oracle-Token: approve
# Payee registry id of the demo seller (services/agent-wallet/config/payees.json). Never an address from text.
SELLER_PAYEE = os.getenv("WALLET_SELLER_PAYEE", "SELLER:siam-fresh-pack")
DEFAULT_MANDATE_ID = "mdt_001"  # the demo mandate the wallet activates at startup
SERVICE = Path(__file__).resolve().parents[1]
PROFILES = json.loads((SERVICE / "samples" / "profiles.json").read_text())
QUOTES = json.loads((SERVICE.parents[1] / "data" / "agent" / "lender_quotes.json").read_text())["quotes"]
CENT = Decimal("0.01")

app = FastAPI(title="orchestrator")
_flows: dict[str, dict] = {}  # invoice_id -> what /flow/repay needs to settle (fingerprint, doc_hash, face)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=60)


async def _post(client: httpx.AsyncClient, url: str, keep_4xx: bool = False, **kwargs) -> dict:
    """POST to a service; a 4xx/5xx from it becomes a 502 that names the service and its reason.
    With keep_4xx, a 4xx keeps its status: ocr-ai's 4xx means the caller's upload is at fault (wrong type,
    too big), not that a service is down."""
    r = await client.post(url, **kwargs)
    if r.status_code >= 400:
        status = r.status_code if keep_4xx and r.status_code < 500 else 502
        raise HTTPException(status_code=status, detail=f"{url} answered {r.status_code}: {r.text[:300]}")
    return r.json()


def select_quote(decision: dict) -> tuple[dict | None, list[dict]]:
    """Mock lender market (scope 4.4): the highest advance whose APR is within the approved pricing; ties go
    to the lower APR. The approved APR is the decision's (policy-ai keeps it inside the mandate), and the
    wallet re-checks it against both the mandate and the approval, so this choice can never loosen either."""
    apr_cap = (
        Decimal(decision["apr"])
        if decision.get("apr") is not None
        else fee_rate_30d_to_apr(Decimal(decision["fee_rate"]))
    )
    eligible = [q for q in QUOTES if Decimal(q["apr"]) <= apr_cap]
    chosen = max(eligible, key=lambda q: (Decimal(q["advance_rate"]), -Decimal(q["apr"])), default=None)
    offers = [
        {
            "lender_id": q["lender_id"],
            "lender": q["name"],
            "advance_rate": q["advance_rate"],
            "apr": q["apr"],
            "within_mandate": q in eligible,
            "chosen": q is chosen,
        }
        for q in QUOTES
    ]
    return chosen, offers


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "orchestrator"}


@app.post("/flow/run")
async def flow_run(file: UploadFile = File(...), mandate_id: str = Form(DEFAULT_MANDATE_ID)) -> dict:
    content = await file.read()
    steps: dict = {"mandate_id": mandate_id}
    agent = {"X-Agent-Token": WALLET_AGENT_TOKEN}
    async with _client() as client:
        invoice = steps["ocr"] = await _post(
            client,
            f"{OCR_URL}/ocr/extract",
            keep_4xx=True,
            files={"file": (file.filename, content, file.content_type)},
        )
        invoice_id, fingerprint = invoice["invoice_id"], invoice["invoice_fingerprint"]

        # TX-1: the on-chain ReceivableRegistry is the duplicate check (a re-saved PDF keeps its fingerprint).
        register = steps["register"] = await _post(
            client,
            f"{WALLET_URL}/wallet/register",
            headers=agent,
            json={
                "idempotency_key": f"{invoice_id}:register",
                "invoice_id": invoice_id,
                "invoice_fingerprint": fingerprint,
                "doc_hash": invoice["doc_hash"],
                "face_value": invoice["amount"],
                "currency": invoice["currency"],
                "due_date": invoice["due_date"],
                "seller": SELLER_PAYEE,
            },
        )
        duplicate = register.get("block_reason") == "DuplicateReceivable"
        steps["registry"] = {"invoice_fingerprint": fingerprint, "duplicate": duplicate}
        if register["status"] != "executed":
            steps["outcome"] = f"blocked: {register.get('block_reason') or register['status']}"
            return steps
        _flows[invoice_id] = {
            "invoice_fingerprint": fingerprint,
            "doc_hash": invoice["doc_hash"],
            "face_value": invoice["amount"],
        }

        decision = steps["policy"] = await _post(
            client, f"{POLICY_URL}/policy/decide", json={"invoice": invoice, **PROFILES}
        )
        if decision["decision"] != "approve":
            steps["outcome"] = f"{decision['decision']}: wallet not called"  # no TX-2, so no draw can pass
            return steps

        # TX-2: the risk oracle records the credit approval; the wallet recomputes decision_hash from it.
        approve = steps["approve"] = await _post(
            client,
            f"{WALLET_URL}/wallet/approve",
            headers={"X-Risk-Oracle-Token": WALLET_RISK_ORACLE_TOKEN},
            json={
                "idempotency_key": f"{invoice_id}:approve",
                "decision_id": decision["decision_id"],
                "decision": decision,
                "decision_hash": decision["decision_hash"],
                "invoice_fingerprint": fingerprint,
                "doc_hash": invoice["doc_hash"],
                "limit": decision["limit"],
                "fee_rate": decision["fee_rate"],
                "model_version": decision["model_version"],
                "policy_version": decision["policy_version"],
            },
        )
        if approve["status"] != "executed":
            steps["outcome"] = f"blocked: {approve.get('block_reason') or approve['status']}"
            return steps

        quote, steps["offers"] = select_quote(decision)
        if quote is None:
            steps["outcome"] = "blocked: no lender quote within the approved APR"
            return steps
        face = Decimal(invoice["amount"])
        amount = min(Decimal(decision["limit"]), (face * Decimal(quote["advance_rate"])).quantize(CENT))

        # TX-4: the draw. The wallet's guard (L0-L4) and the chain's PolicyGuard both check it before paying.
        wallet = steps["wallet"] = await _post(
            client,
            f"{WALLET_URL}/wallet/execute",
            headers=agent,
            json={
                "idempotency_key": f"{invoice_id}:draw",
                "decision": decision,
                "decision_id": decision["decision_id"],
                "decision_hash": decision["decision_hash"],
                "invoice_id": invoice_id,
                "invoice_fingerprint": fingerprint,
                "doc_hash": invoice["doc_hash"],
                "payee": SELLER_PAYEE,
                "amount": str(amount),
                "currency": invoice["currency"],
                "apr": quote["apr"],
                "lender_id": quote["lender_id"],
                "mandate_id": mandate_id,
            },
        )
    steps["outcome"] = wallet["status"]
    return steps


@app.post("/flow/repay")
async def flow_repay(
    invoice_id: str = Form(...), amount_paid: str | None = Form(None), paid_at: str | None = Form(None)
) -> dict:
    """Simulates "buyer paid": TX-5 settle through the wallet. Defaults to the full face value, paid today."""
    flow = _flows.get(invoice_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=f"unknown invoice_id {invoice_id}: run /flow/run first")
    paid = (Decimal(amount_paid) if amount_paid else Decimal(flow["face_value"])).quantize(
        CENT, ROUND_HALF_UP
    )
    async with _client() as client:
        result = await _post(
            client,
            f"{WALLET_URL}/wallet/settle",
            headers={"X-Agent-Token": WALLET_AGENT_TOKEN},
            json={
                "idempotency_key": f"{invoice_id}:settle",
                "invoice_id": invoice_id,
                "invoice_fingerprint": flow["invoice_fingerprint"],
                "doc_hash": flow["doc_hash"],
                "amount_paid": str(paid),
                "paid_at": paid_at,
            },
        )
    return {"invoice_id": invoice_id, "amount_paid": str(paid), **result}
