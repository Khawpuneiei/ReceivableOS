"""orchestrator: end-to-end ReceivableOS flow (scope 4.4). Owner: PM.

POST /flow/run: invoice -> ocr-ai -> policy-ai -> lender quote -> agent-wallet
(register TX-1, approve TX-2 when the policy says approve, execute TX-4).
POST /flow/repay: buyer paid -> agent-wallet settle (TX-5).

Both POST endpoints need the caller's X-Orchestrator-Token. This service holds the wallet tokens, so without
it anyone who can reach the port could move money. Progress is kept per invoice (an in-memory stand-in for
the ReceivableRegistry): a retry resumes from the last step that succeeded, and the wallet's idempotency keys
make a repeated call safe. The wallet's register is the on-chain duplicate check.
Lender quotes are the mock lenders in samples/lenders.json (CLAUDE.md section 1).
"""

import hmac
import json
import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile

OCR_URL = os.getenv("OCR_URL", "http://localhost:8001")
POLICY_URL = os.getenv("POLICY_URL", "http://localhost:8002")
WALLET_URL = os.getenv("WALLET_URL", "http://localhost:8003")
ORCHESTRATOR_TOKEN = os.getenv("ORCHESTRATOR_TOKEN", "")  # the caller's token for /flow/run and /flow/repay
WALLET_AGENT_TOKEN = os.getenv("WALLET_AGENT_TOKEN", "")  # register, execute and settle
WALLET_RISK_ORACLE_TOKEN = os.getenv("WALLET_RISK_ORACLE_TOKEN", "")  # approve (TX-2) only
MAX_APR = Decimal(os.getenv("MAX_APR", "0.12"))  # the demo mandate's max_apr; the wallet checks it again
DEFAULT_MANDATE_ID = "mdt_001"  # the demo mandate the wallet activates at startup
SELLER_ID = "SELLER:siam-fresh-pack"  # a payee registry id, never an address
SAMPLES = Path(__file__).resolve().parents[1] / "samples"
PROFILES = json.loads((SAMPLES / "profiles.json").read_text())
LENDERS = json.loads((SAMPLES / "lenders.json").read_text())["quotes"]

app = FastAPI(title="orchestrator")
# invoice_fingerprint -> progress. step: "registered" | "approved" | "executed" | "pending_approval".
# Only invoices the wallet has accepted are stored, so a declined or failed first attempt starts again.
_flows: dict[str, dict] = {}


def check_caller(x_orchestrator_token: str | None = Header(default=None)) -> None:
    """Fails closed: with no ORCHESTRATOR_TOKEN configured, every caller is refused."""
    if not ORCHESTRATOR_TOKEN or not x_orchestrator_token:
        raise HTTPException(status_code=403, detail="Unauthorized")
    if not hmac.compare_digest(ORCHESTRATOR_TOKEN, x_orchestrator_token):
        raise HTTPException(status_code=403, detail="Unauthorized")


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


def parse_amount_paid(raw: str | None, face: str) -> str:
    """The buyer's payment. Absent means the full face value. It must be a positive amount with at most two
    decimals, and not above the face value. A short payment is allowed: the wallet's waterfall flags it."""
    if raw is None or raw == "":
        return face
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise HTTPException(status_code=422, detail="amount_paid must be a decimal amount") from None
    if not amount.is_finite() or amount <= 0 or amount > Decimal(face):
        raise HTTPException(status_code=422, detail=f"amount_paid must be above 0 and at most {face}")
    if amount != amount.quantize(Decimal("0.01")):
        raise HTTPException(status_code=422, detail="amount_paid has more than 2 decimals")
    return f"{amount:.2f}"


async def call_service(
    client: httpx.AsyncClient,
    service: str,
    url: str,
    *,
    headers: dict | None = None,
    json_body: dict | None = None,
    files: dict | None = None,
) -> tuple[int, dict]:
    """POST to an upstream service. An unreachable service is reported as HTTP 503, not raised."""
    try:
        r = await client.post(url, headers=headers or {}, json=json_body, files=files)
    except httpx.HTTPError:
        return 503, {"detail": f"{service} unreachable"}
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"detail": r.text[:200]}


def http_problem(service: str, status: int, body: dict) -> str | None:
    """Why an upstream call failed, or None when it did not fail at the HTTP level."""
    if status >= 400:
        return f"failed: {service} returned HTTP {status}: {body.get('detail', '')}"
    return None


def wallet_problem(status: int, body: dict) -> str | None:
    """Why the wallet did not carry out the step, or None when it did (or is waiting for an approver).
    A 2xx without a status is not a result the flow can use, so it counts as a failure."""
    if problem := http_problem("wallet", status, body):
        return problem
    if "status" not in body:
        return "failed: wallet returned no status"
    if body["status"] in ("blocked", "failed"):
        return f"{body['status']}: {body.get('block_reason') or 'no reason given'}"
    return None


@app.post("/flow/run", dependencies=[Depends(check_caller)])
async def flow_run(file: UploadFile = File(...), mandate_id: str = Form(DEFAULT_MANDATE_ID)) -> dict:
    content = await file.read()
    steps: dict = {"mandate_id": mandate_id}
    agent = {"X-Agent-Token": WALLET_AGENT_TOKEN}
    oracle = {"X-Risk-Oracle-Token": WALLET_RISK_ORACLE_TOKEN}
    async with httpx.AsyncClient(timeout=60) as client:
        status, invoice = await call_service(
            client, "ocr-ai", f"{OCR_URL}/ocr/extract", files={"file": (file.filename, content)}
        )
        if problem := http_problem("ocr-ai", status, invoice):
            steps["outcome"] = problem
            return steps
        steps["ocr"] = invoice
        invoice_id = invoice["invoice_id"]
        key = invoice["invoice_fingerprint"]

        flow = _flows.get(key)
        steps["registry"] = {"invoice_fingerprint": key, "resumed": flow is not None}
        if flow is not None and flow["step"] == "executed":
            steps["outcome"] = "blocked: invoice already financed"
            return steps
        if flow is not None and flow["step"] == "pending_approval":
            steps["outcome"] = "pending_approval: waiting for the approver"
            return steps

        if flow is None:
            status, decision = await call_service(
                client,
                "policy-ai",
                f"{POLICY_URL}/policy/decide",
                json_body={"invoice": invoice, **PROFILES},
            )
            if problem := http_problem("policy-ai", status, decision):
                steps["outcome"] = problem
                return steps
            steps["policy"] = decision
            if decision["decision"] != "approve":
                steps["outcome"] = f"not financed: policy decision is {decision['decision']}"
                return steps
            status, body = await call_service(
                client,
                "wallet",
                f"{WALLET_URL}/wallet/register",
                headers=agent,
                json_body={
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
            flow = _flows[key] = {
                "invoice_id": invoice_id,
                "invoice_fingerprint": key,
                "doc_hash": invoice["doc_hash"],
                "face": invoice["amount"],
                "currency": invoice["currency"],
                "decision": decision,
                "step": "registered",
                "quote": None,
            }
        else:
            # A retry: the decision the wallet already holds is reused, so the hashes still match.
            decision = flow["decision"]
            steps["policy"] = decision

        if flow["step"] == "registered":
            status, body = await call_service(
                client,
                "wallet",
                f"{WALLET_URL}/wallet/approve",
                headers=oracle,
                json_body={
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
            flow["step"] = "approved"

        if flow["quote"] is None:
            flow["quote"] = select_quote(Decimal(flow["face"]), Decimal(decision["limit"]))
            if flow["quote"] is None:
                steps["outcome"] = "blocked: no lender quote within the mandate's APR cap"
                return steps
        quote = steps["quote"] = flow["quote"]

        status, body = await call_service(
            client,
            "wallet",
            f"{WALLET_URL}/wallet/execute",
            headers=agent,
            json_body={
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
        if body.get("status") in ("executed", "pending_approval"):
            flow["step"] = body["status"]
    return steps


@app.post("/flow/repay", dependencies=[Depends(check_caller)])
async def flow_repay(invoice_id: str = Form(...), amount_paid: str | None = Form(None)) -> dict:
    flow = next((f for f in _flows.values() if f["invoice_id"] == invoice_id), None)
    if flow is None or flow["step"] != "executed":
        return {"invoice_id": invoice_id, "outcome": "not settled: no executed draw for this invoice"}
    paid = parse_amount_paid(amount_paid, flow["face"])
    async with httpx.AsyncClient(timeout=60) as client:
        status, body = await call_service(
            client,
            "wallet",
            f"{WALLET_URL}/wallet/settle",
            headers={"X-Agent-Token": WALLET_AGENT_TOKEN},
            json_body={
                "idempotency_key": f"{invoice_id}:settle",
                "invoice_id": invoice_id,
                "invoice_fingerprint": flow["invoice_fingerprint"],
                "doc_hash": flow["doc_hash"],
                "amount_paid": paid,
            },
        )
    return {
        "invoice_id": invoice_id,
        "settle": body,
        "outcome": wallet_problem(status, body) or body["status"],
    }
